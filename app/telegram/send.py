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


_carousels: dict[str, list] = {}   # chat id -> candidates currently shown (in memory, lost on restart)


def _card_markup(candidates: list, i: int) -> dict:
    nav = [
        {"text": "<", "callback_data": f"nav:{(i - 1) % len(candidates)}"},
        {"text": f"{i + 1}/{len(candidates)}", "callback_data": f"nav:{i}"},
        {"text": ">", "callback_data": f"nav:{(i + 1) % len(candidates)}"},
    ]
    buy = [_button("Buy", f"BUY:{candidates[i].product_id}")]
    return {"inline_keyboard": [nav, buy] if len(candidates) > 1 else [buy]}


async def _send_card(chat_id: str, candidates: list, i: int) -> None:
    c, markup, text = candidates[i], _card_markup(candidates, i), _caption(candidates[i])
    try:
        if not c.image_url:
            raise TelegramError("no image")
        await call("sendPhoto", chat_id=chat_id, photo=c.image_url, caption=text[:1000], reply_markup=markup)
    except TelegramError:
        # Telegram rejects some image URLs (size, format). The product is still buyable.
        await call("sendMessage", chat_id=chat_id, text=text, reply_markup=markup)


async def send_cards(chat_id: str, candidates) -> None:
    """Telegram has no carousel: one swipeable card, the < > buttons edit it in place."""
    cands = list(candidates[:10])
    if not cands:
        return
    _carousels[chat_id] = cands
    await _send_card(chat_id, cands, 0)


async def show_card(chat_id: str, message_id: int, i: int) -> None:
    """Handle a < > tap: swap the card in place, or resend it if Telegram refuses the edit."""
    cands = _carousels.get(chat_id)
    if not cands or not 0 <= i < len(cands):
        await send_text(chat_id, "Those results have expired. Send the reel link again.")
        return
    c, markup, text = cands[i], _card_markup(cands, i), _caption(cands[i])
    try:
        if not c.image_url:
            raise TelegramError("no image")
        await call(
            "editMessageMedia", chat_id=chat_id, message_id=message_id, reply_markup=markup,
            media={"type": "photo", "media": c.image_url, "caption": text[:1000]},
        )
    except TelegramError:
        # Text cards cannot become photo cards (or the image was rejected): replace the message.
        try:
            await call("deleteMessage", chat_id=chat_id, message_id=message_id)
        except TelegramError:
            pass
        await _send_card(chat_id, cands, i)


async def send_carousel(chat_id: str, result) -> None:
    await send_cards(chat_id, result.candidates)
