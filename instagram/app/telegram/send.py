import logging

from app import state
from app.telegram.api import TelegramError, call

log = logging.getLogger("telegram")


def _button(title: str, payload: str) -> dict:
    return {"text": title[:60], "callback_data": "c:" + state.put_callback(payload)}


def _rows(buttons: list[dict], per_row: int = 2) -> list[list[dict]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


async def send_text(chat_id: str, text: str) -> None:
    await call("sendMessage", chat_id=chat_id, text=text[:4000])


async def send_quick_replies(chat_id: str, text: str, options: list[tuple[str, str]]) -> None:
    """(title, payload) pairs become an inline keyboard, two buttons per row."""
    buttons = [_button(t, p) for t, p in options]
    await call(
        "sendMessage", chat_id=chat_id, text=text[:4000],
        reply_markup={"inline_keyboard": _rows(buttons)},
    )


async def send_url_button(chat_id: str, text: str, title: str, url: str) -> None:
    await call(
        "sendMessage", chat_id=chat_id, text=text[:4000],
        reply_markup={"inline_keyboard": [[{"text": title[:60], "url": url}]]},
    )


def _caption(c) -> str:
    price = f"{c.price_min:g}" if c.price_min == c.price_max else f"{c.price_min:g}-{c.price_max:g}"
    lines = []
    if getattr(c, "badge", None):
        lines.append(f"* {c.badge}")
    lines += [c.name[:200], f"{c.merchant[:60]} | {c.currency} {price}"]
    return "\n".join(lines)


async def send_cards(chat_id: str, candidates) -> None:
    """Telegram has no carousel: one photo per product with a Buy button, in ranked order."""
    for c in candidates[:10]:
        markup = {"inline_keyboard": [[_button("Buy", f"BUY:{c.product_id}")]]}
        text = _caption(c)
        try:
            if not c.image_url:
                raise TelegramError("no image")
            await call("sendPhoto", chat_id=chat_id, photo=c.image_url, caption=text[:1000], reply_markup=markup)
        except TelegramError:
            # Telegram rejects some image URLs (size, format). The product is still buyable.
            await call("sendMessage", chat_id=chat_id, text=text, reply_markup=markup)


async def send_carousel(chat_id: str, result) -> None:
    await send_cards(chat_id, result.candidates)
