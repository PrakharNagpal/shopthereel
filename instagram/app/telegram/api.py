import logging
from typing import Any

import httpx

from app.config import settings

# httpx logs full request URLs at INFO, and Telegram puts the bot token in the URL path.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_client: httpx.AsyncClient | None = None


class TelegramError(Exception):
    pass


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=40)
    return _client


async def call(method: str, **params: Any) -> Any:
    """Bot API call. Errors are re-raised without the URL, which contains the token."""
    if not settings.telegram_bot_token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"
    try:
        resp = await _http().post(url, json=params)
        data = resp.json()
    except Exception as e:
        raise TelegramError(f"{method} failed: {type(e).__name__}") from None
    if not data.get("ok"):
        raise TelegramError(f"{method} failed: {data.get('description', 'unknown error')}")
    return data["result"]
