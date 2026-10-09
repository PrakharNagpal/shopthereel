"""Long-polling receiver: no public URL or ngrok needed for Telegram."""
import asyncio
import logging

from app.config import settings
from app.dm.router import handle_events
from app.telegram.api import TelegramError, call
from app.telegram.parse import parse_update

log = logging.getLogger("telegram")

# Quick replies that start something irreversible or one-shot lose their buttons once tapped,
# so a double tap cannot confirm twice. BUY stays tappable (the user may need to tap it again).
KEEP_BUTTONS = ("BUY:",)


def _allowed(chat_id: str) -> bool:
    ids = {x.strip() for x in settings.telegram_allowed_chat_ids.split(",") if x.strip()}
    return not ids or chat_id in ids


async def _ack(u: dict, ev) -> None:
    cb = u.get("callback_query")
    if not cb:
        return
    try:
        await call("answerCallbackQuery", callback_query_id=cb["id"])
        if ev and not (ev.payload or "").startswith(KEEP_BUTTONS):
            msg = cb["message"]
            await call(
                "editMessageReplyMarkup", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                reply_markup={"inline_keyboard": []},
            )
    except TelegramError:
        pass  # message too old to edit, or already answered


async def handle_update(u: dict) -> None:
    ev = parse_update(u)
    chat = (u.get("message") or (u.get("callback_query") or {}).get("message") or {}).get("chat", {})
    cid = str(chat.get("id", ""))
    if cid and not _allowed(cid):
        log.warning("ignored message from chat id %s (not in TELEGRAM_ALLOWED_CHAT_IDS)", cid)
        return
    await _ack(u, ev)
    if ev is None:
        if u.get("callback_query") and cid:
            await call("sendMessage", chat_id=cid, text="That button has expired. Send the reel link again.")
        return
    await handle_events([ev])


async def run() -> None:
    me = await call("getMe")
    log.info("telegram bot @%s is polling", me.get("username"))
    offset = None
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
            if offset is not None:
                params["offset"] = offset
            updates = await call("getUpdates", **params)
        except TelegramError as e:
            log.warning("poll error: %s", e)
            await asyncio.sleep(3)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                await handle_update(u)
            except Exception:
                log.exception("update failed")
