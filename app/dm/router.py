import asyncio
import json
import logging

from app import state
from app.config import settings
from app.agent.conversation import respond, remember_reel, read_context, write_context, record_inventory
from app.agent.search import gather_candidates, recognize_and_search
from app.agent.profile import describe_profile, excluded, load_profile, update_profile
from app.agent.personalize import advise, mock_air_fryer_scene
from app.dm import render
from app.dm import settings as rules_menu
from app.media.pipeline import bundle_from_url
from app.meta.parse import InboundEvent, parse_events
from app.messaging import send_quick_replies, send_text, send_url_button
from app.models import DetectedProduct, ProductCandidate, RecognitionResult
from app.purchase import policy, service
from app.purchase.budget import handle_budget_command
from app.reap.client import ReapError

log = logging.getLogger("router")

_last_reel: dict[str, InboundEvent] = {}   # igsid -> most recent reel, for text hints
_tasks: set[asyncio.Task] = set()          # keep refs so background tasks are not GC'd
_personal_advice: dict[str, dict] = {}


def spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def handle_payload(body: dict) -> None:
    """Instagram webhook body."""
    await handle_events(parse_events(body))


async def handle_events(events: list[InboundEvent]) -> None:
    for ev in events:
        if ev.mid and not state.first_time_seen(ev.mid):
            continue  # webhook retry
        try:
            await dispatch(ev)
        except ReapError as e:
            log.warning("reap error: %s", e)
            await send_text(ev.igsid, service.friendly_error(e))
        except Exception:
            log.exception("handler failed")
            await send_text(ev.igsid, "Sorry, something went wrong. Please try again.")


async def dispatch(ev: InboundEvent) -> None:
    if ev.kind == "reel":
        _last_reel[ev.igsid] = ev
        await send_text(ev.igsid, "Looking at this reel 👀")
        spawn(process_reel(ev, None))
    elif ev.kind == "text":
        await handle_text(ev)
    elif ev.payload:
        await handle_payload_tap(ev)


async def process_reel(ev: InboundEvent, hint: str | None) -> None:
    try:
        if not settings.reap_api_key or not settings.reap_version:
            await send_text(
                ev.igsid,
                "Telegram is connected. Product search is waiting for the Reap sandbox "
                "API key and API version to be configured. No purchase was attempted.",
            )
            return
        if not ev.reel_url:
            raise ValueError("no reel url")
        bundle = await bundle_from_url(ev.reel_url, ev.reel_id or "unknown", ev.reel_title, hint)
        result = await recognize_and_search(bundle, user_id=ev.igsid)
        await add_personal_advice(ev.igsid, bundle, result)
        await render.results(ev.igsid, result)
        await offer_oven_option(ev.igsid)
    except Exception:
        log.exception("reel processing failed")
        await send_text(
            ev.igsid, "I couldn't process that reel. Try another one, or describe the item to me."
        )


async def handle_text(ev: InboundEvent) -> None:
    text = (ev.text or "").strip()
    if text.lower() == "profile":
        await send_text(ev.igsid, describe_profile(ev.igsid))
        return
    if text.lower().startswith("profile set "):
        field, _, value = text[12:].partition(" ")
        try:
            update_profile(ev.igsid, field.lower(), value)
            await send_text(ev.igsid, describe_profile(ev.igsid))
        except ValueError as e:
            await send_text(ev.igsid, str(e))
        return
    if text.lower() == "demo air fryer":
        await send_text(ev.igsid, "Demo scene: air-fryer baked oats. Recognition is mocked; "
                        "personal advice and catalog search are live. Checking your demo profile.")
        spawn(run_personal_demo(ev.igsid))
        return
    if text.lower() == "use my oven":
        await oven_alternative(ev.igsid)
        return
    if text.lower().startswith("search "):
        query = text[7:].strip()
        response = await service.client().search_products(query)
        candidates = []
        for p in response.get("products", []):
            price = p.get("priceRange", {})
            low = price.get("min", {})
            high = price.get("max", low)
            merchant = p.get("merchant", {})
            candidates.append(ProductCandidate(
                product_id=p["id"], name=p["name"],
                merchant=merchant.get("name", "Store") if isinstance(merchant, dict) else str(merchant),
                price_min=low.get("amount", 0), price_max=high.get("amount", 0),
                currency=low.get("currency", settings.reap_default_currency),
            ))
        profile = load_profile(ev.igsid)
        candidates = [c for c in candidates if not excluded(c.name, profile)]
        await render.results(ev.igsid, RecognitionResult(
            detected=DetectedProduct(name=query, category="search", brand_source="none",
                                     attributes=[], queries=[query], best_frame=0, confidence=1),
            match_type="similar" if candidates else "none", candidates=candidates,
            note="Catalog search results. Sandbox demo only.",
        ))
        return
    if await rules_menu.handle_text(ev.igsid, text):
        return
    reply = handle_budget_command(ev.igsid, text)
    if reply:
        await send_text(ev.igsid, reply)
    elif text.lower() in ("help", "hi", "hello", "start"):
        await send_text(ev.igsid, render.HELP)
    else:
        spawn(converse(ev.igsid, text))


async def converse(uid: str, text: str) -> None:
    action = await respond(uid, text)
    if action.get("intent") == "remember":
        await send_quick_replies(uid, action["reply"], [("Yes, remember", f"INVENTORY:yes:{action['nonce']}"), ("Cancel", f"INVENTORY:no:{action['nonce']}")])
    else:
        await send_text(uid, action["reply"])
    if action.get("intent") == "search" and action.get("query"):
        try:
            pooled = await gather_candidates([action["query"][:200]])
        except Exception:
            await send_text(uid, "Catalog search is unavailable right now. Please try again.")
            return
        candidates = [c for _, c in pooled if not excluded(c.name, load_profile(uid))][:8]
        if candidates:
            from app.messaging import send_cards
            await send_cards(uid, candidates)
        else:
            await send_text(uid, "No matching products came back from the catalog. Try another description.")


async def handle_payload_tap(ev: InboundEvent) -> None:
    kind, _, rest = (ev.payload or "").partition(":")
    uid = ev.igsid
    if kind == "INVENTORY":
        context = read_context(uid)
        decision, _, nonce = rest.partition(":")
        pending = context.get("pending_inventory")
        if not pending or pending.get("nonce") != nonce:
            await send_text(uid, "That update has expired. Tell me what you have again.")
        elif decision == "yes":
            context.pop("pending_inventory", None)
            write_context(uid, context)
            pending.pop("nonce", None)
            record_inventory(uid, **pending)
            await send_text(uid, f"Saved: you {'have' if pending['present'] else 'do not have'} {pending['item']}. Future advice will use this.")
        else:
            context.pop("pending_inventory", None)
            write_context(uid, context)
            await send_text(uid, "Your inventory was not changed.")
    elif kind in ("SET", "SETVAL"):
        await rules_menu.handle_tap(uid, ev.payload)
    elif kind == "BUY":
        state.update_user(uid, pending_product_id=rest, pending_option_ids="[]")
        await remember_product_name(uid, rest)
        await card_gate(uid)
    elif kind == "OPT":
        product_id, _, option_id = rest.partition(":")
        picked = json.loads(state.get_user(uid).get("pending_option_ids") or "[]")
        state.update_user(uid, pending_option_ids=json.dumps(picked + [option_id]))
        await next_step(uid)
    elif kind in ("CONFIRM", "CONFIRMX"):
        u = state.get_user(uid)
        amount = u.get("pending_quote_amount") or 0
        # Large orders need a second, explicit tap (CONFIRMX) before any checkout is created.
        if kind == "CONFIRM" and policy.needs_extra_confirm(uid, amount):
            await send_quick_replies(
                uid, f"This is a large order: {amount:.2f}. Are you sure you want to buy it?",
                [("Yes, buy it", f"CONFIRMX:{rest}"), ("Cancel", "CANCEL")],
            )
            return
        order = await service.start_checkout(uid, rest)
        if order.approval_url:
            await send_url_button(
                uid, "Approve the payment on Reap's secure page:", "Approve payment",
                order.approval_url,
            )
        spawn(service.watch_checkout(uid, order.checkout_id))
    elif kind == "NEWCARD":
        await card_gate(uid, new_link=True)
    elif kind == "OVEN":
        await oven_alternative(uid, rest)
    elif kind == "OVENSHOP":
        await oven_shopping(uid, rest)
    elif kind == "SKIP":
        await send_text(uid, "No problem. Share another reel any time.")
    elif kind == "CANCEL":
        state.update_user(
            uid, pending_product_id=None, pending_option_ids=None,
            pending_quote_id=None, pending_variant_id=None,
        )
        await send_text(uid, "Cancelled. Nothing was charged.")


async def add_personal_advice(uid: str, bundle, result) -> None:
    advice = await advise(bundle, result.detected, uid, result.candidates)
    preferred = []
    for index in advice.get("recommended_indices", []):
        if isinstance(index, int) and 0 <= index < len(result.candidates) and index not in preferred:
            preferred.append(index)
    if preferred:
        preferred += [i for i in range(len(result.candidates)) if i not in preferred]
        result.candidates = [result.candidates[i] for i in preferred]
        result.candidates[0].badge = "For your profile"
    _personal_advice[uid] = {**advice, "reel_id": bundle.reel_id}
    remember_reel(uid, bundle, result, advice)
    sample_fields = load_profile(uid).get("sample_fields", [])
    disclaimer = ("Demo assumptions: " + ", ".join(sample_fields) + ". Type 'profile' to review or edit.") if sample_fields and advice.get("note") else None
    result.note = "\n\n".join(n for n in (result.note, disclaimer, advice.get("note")) if n) or None


async def offer_oven_option(uid: str) -> None:
    advice = _personal_advice.get(uid, {})
    if advice.get("oven_alternative"):
        await send_quick_replies(uid, "You can also cook with what you already own.",
                                [("Use my oven", f"OVEN:{advice['reel_id']}")])


async def oven_alternative(uid: str, reel_id: str | None = None) -> None:
    advice = _personal_advice.get(uid, {})
    if not advice.get("oven_alternative") or (reel_id and advice.get("reel_id") != reel_id):
        await send_text(uid, "Send the recipe Reel again, or try 'demo air fryer', so I can adapt it.")
        return
    await send_text(uid, advice["oven_alternative"])
    if advice.get("alternative_queries"):
        await send_quick_replies(uid, "Want me to check the catalog for missing items? "
                                "Confirm what is in your pantry before buying.",
                                [("Browse missing items", f"OVENSHOP:{advice['reel_id']}")])


async def oven_shopping(uid: str, reel_id: str) -> None:
    advice = _personal_advice.get(uid, {})
    if advice.get("reel_id") != reel_id:
        await send_text(uid, "Those suggestions have expired. Send the recipe again.")
        return
    queries = advice.get("alternative_queries", [])
    await send_text(uid, "Checking recipe suggestions in the live catalog. These are individual "
                    "items, not a complete ingredient basket.")
    pooled = await gather_candidates(queries)
    profile = load_profile(uid)
    from app.messaging import send_cards
    candidates = [c for _, c in pooled if not excluded(c.name, profile)][:8]
    if candidates:
        await send_cards(uid, candidates)
    else:
        await send_text(uid, "No matching items came back. You can still use the oven method.")


async def run_personal_demo(uid: str) -> None:
    try:
        bundle, detected = mock_air_fryer_scene()
        pooled = await gather_candidates(detected.queries)
        candidates = [c for _, c in pooled if not excluded(c.name, load_profile(uid))][:8]
        result = RecognitionResult(detected=detected, match_type="similar" if candidates else "none",
                                   candidates=candidates, note="Demo recognition; live catalog results.")
        await add_personal_advice(uid, bundle, result)
        await render.results(uid, result)
        await offer_oven_option(uid)
    except Exception:
        log.warning("Personal demo could not complete")
        await send_text(uid, "The demo could not complete. Try again, or type 'profile' to review your setup.")


_watching: set[str] = set()   # enrollment ids that have a card-verification watcher running


async def card_gate(uid: str, new_link: bool = False) -> None:
    """Continue the purchase if a card is ready, otherwise get one set up without dead ends."""
    st = await service.enrollment_state(uid)
    if st == "ACTIVE":
        await next_step(uid)
        return
    if st == "PENDING" and not new_link:
        await send_quick_replies(
            uid,
            "Reap is still verifying your card, which can take a few minutes. "
            "I will carry on with your order as soon as it is ready.",
            [("Send a new link", "NEWCARD")],
        )
    else:
        url = await service.ensure_enrollment(uid)
        if url is None:  # became active in the meantime
            await next_step(uid)
            return
        await send_url_button(
            uid, "First, add a card securely with Reap. I never see your card details.",
            "Add card", url,
        )
        await send_text(uid, "When you are done I will continue automatically.")
    eid = state.get_user(uid).get("enrollment_id")
    if eid and eid not in _watching:
        _watching.add(eid)
        spawn(watch_enrollment(uid, eid))


async def watch_enrollment(uid: str, eid: str, timeout_s: int = 1200) -> None:
    """Poll one enrollment; when Reap activates the card, resume the user's pending order."""
    try:
        for _ in range(timeout_s // 5):
            await asyncio.sleep(5)
            if state.get_user(uid).get("enrollment_id") != eid:
                return  # replaced by a newer link, whose own gate will watch it
            try:
                status = (await service.client().get_enrollment(eid)).get("status")
            except ReapError:
                continue
            if status == "ACTIVE":
                await send_text(uid, "Your card is ready. Carrying on with your order.")
                try:
                    await next_step(uid)
                except ReapError as e:
                    await send_text(uid, service.friendly_error(e))
                return
            if status in ("FAILED", "EXPIRED", "REVOKED"):
                await send_text(uid, "Card setup did not complete. Tap Buy again to get a new link.")
                return
    finally:
        _watching.discard(eid)


async def remember_product_name(uid: str, product_id: str) -> None:
    """Needed later for add-on suggestions. A failure here must never block the purchase."""
    try:
        det = await service.client().product_details([product_id])
        state.update_user(uid, pending_product_name=det["products"][0]["name"])
    except Exception:
        log.warning("could not look up product name")


async def next_step(uid: str) -> None:
    """Ask the next unanswered option group, or resolve the variant and quote."""
    u = state.get_user(uid)
    product_id = u["pending_product_id"]
    picked = set(json.loads(u.get("pending_option_ids") or "[]"))
    groups: dict[str, list] = {}
    for o in await service.get_options(product_id):
        if o.available:
            groups.setdefault(o.group, []).append(o)

    chosen = list(picked)
    for name, opts in groups.items():
        if any(o.option_id in picked for o in opts):
            continue
        if len(opts) == 1:
            chosen.append(opts[0].option_id)
            continue
        await send_quick_replies(
            uid, f"Which {name.lower()}?",
            [(o.label, f"OPT:{product_id}:{o.option_id}") for o in opts],
        )
        return

    variant_id = await service.resolve_variant(product_id, chosen)
    q = await service.create_quote(uid, variant_id)
    await render.quote(uid, q)
