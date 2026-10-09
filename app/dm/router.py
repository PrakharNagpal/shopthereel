import asyncio
import json
import logging

from app import state
from app.agent.search import recognize_and_search
from app.dm import render
from app.dm import settings as rules_menu
from app.media.pipeline import bundle_from_url
from app.meta.parse import InboundEvent, parse_events
from app.messaging import send_quick_replies, send_text, send_url_button
from app.purchase import policy, service
from app.purchase.budget import handle_budget_command
from app.reap.client import ReapError

log = logging.getLogger("router")

_last_reel: dict[str, InboundEvent] = {}   # igsid -> most recent reel, for text hints
_tasks: set[asyncio.Task] = set()          # keep refs so background tasks are not GC'd


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
        if not ev.reel_url:
            raise ValueError("no reel url")
        bundle = await bundle_from_url(ev.reel_url, ev.reel_id or "unknown", ev.reel_title, hint)
        result = await recognize_and_search(bundle, user_id=ev.igsid)
        await render.results(ev.igsid, result)
    except Exception:
        log.exception("reel processing failed")
        await send_text(
            ev.igsid, "I couldn't process that reel. Try another one, or describe the item to me."
        )


async def handle_text(ev: InboundEvent) -> None:
    text = (ev.text or "").strip()
    if await rules_menu.handle_text(ev.igsid, text):
        return
    reply = handle_budget_command(ev.igsid, text)
    if reply:
        await send_text(ev.igsid, reply)
    elif text.lower() in ("help", "hi", "hello", "start"):
        await send_text(ev.igsid, render.HELP)
    elif ev.igsid in _last_reel:
        await send_text(ev.igsid, f"Got it, looking for: {text}")
        spawn(process_reel(_last_reel[ev.igsid], text))
    else:
        await send_text(ev.igsid, render.HELP)


async def handle_payload_tap(ev: InboundEvent) -> None:
    kind, _, rest = (ev.payload or "").partition(":")
    uid = ev.igsid
    if kind in ("SET", "SETVAL"):
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
    elif kind == "SKIP":
        await send_text(uid, "No problem. Share another reel any time.")
    elif kind == "CANCEL":
        state.update_user(
            uid, pending_product_id=None, pending_option_ids=None,
            pending_quote_id=None, pending_variant_id=None,
        )
        await send_text(uid, "Cancelled. Nothing was charged.")


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
