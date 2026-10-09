import re
from typing import Optional

from app import state
from app.meta.parse import InboundEvent

# https://www.instagram.com/reel/<code>/, /reels/<code>, /p/<code>, /tv/<code>, /<user>/reel/<code>
IG_LINK = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:reel|reels|p|tv)/([\w-]+)[^\s]*", re.I
)


def parse_update(u: dict) -> Optional[InboundEvent]:
    """Telegram update -> InboundEvent. The chat id plays the role of the Instagram user id."""
    cb = u.get("callback_query")
    if cb:
        data = cb.get("data") or ""
        chat_id = (cb.get("message") or {}).get("chat", {}).get("id")
        payload = state.get_callback(data[2:]) if data.startswith("c:") else None
        if chat_id is None or payload is None:
            return None
        return InboundEvent(
            igsid=str(chat_id), kind="quick_reply", mid=f"cb-{u['update_id']}", payload=payload
        )

    msg = u.get("message")
    if not msg or not msg.get("text"):
        return None  # stickers, photos, joins, edits: ignore
    chat_id = msg["chat"]["id"]
    mid = f"{chat_id}-{msg['message_id']}"
    text = msg["text"].strip()

    m = IG_LINK.search(text)
    if m:
        rest = IG_LINK.sub("", text).strip() or None
        return InboundEvent(
            igsid=str(chat_id), kind="reel", mid=mid, reel_url=m.group(0),
            reel_id=m.group(1), text=rest,
        )
    if text.startswith("/"):  # "/settings", "/start@MyBot" behave like the plain word
        text = text[1:].split("@")[0]
    return InboundEvent(igsid=str(chat_id), kind="text", mid=mid, text=text)
