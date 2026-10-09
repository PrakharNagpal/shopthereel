import asyncio
import json
import logging

from app import state
from app.agent.search import recognize_and_search
from app.dm import render
from app.media.pipeline import bundle_from_url
from app.meta.parse import InboundEvent, parse_events
from app.meta.send import send_quick_replies, send_text, send_url_button
from app.purchase import service
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
    for ev in parse_events(body):
        if ev.mid and not state.first_time_seen(ev.mid):
            continue  # webhook retry
        try:
            await dispatch(ev)
        except ReapError as e:
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
    if kind == "BUY":
        state.update_user(uid, pending_product_id=rest, pending_option_ids="[]")
        url = await service.ensure_enrollment(uid)
        if url:
            await send_url_button(
                uid, "First, add a card securely with Reap. I never see your card details.",
                "Add card", url,
            )
            await send_text(uid, "Once you are done, tap Buy on the product again.")
            return
        await next_step(uid)
    elif kind == "OPT":
        product_id, _, option_id = rest.partition(":")
        picked = json.loads(state.get_user(uid).get("pending_option_ids") or "[]")
        state.update_user(uid, pending_option_ids=json.dumps(picked + [option_id]))
        await next_step(uid)
    elif kind == "CONFIRM":
        order = await service.start_checkout(uid, rest)
        if order.approval_url:
            await send_url_button(
                uid, "Approve the payment on Reap's secure page:", "Approve payment",
                order.approval_url,
            )
        spawn(service.watch_checkout(uid, order.checkout_id))
    elif kind == "CANCEL":
        state.update_user(
            uid, pending_product_id=None, pending_option_ids=None,
            pending_quote_id=None, pending_variant_id=None,
        )
        await send_text(uid, "Cancelled. Nothing was charged.")


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
