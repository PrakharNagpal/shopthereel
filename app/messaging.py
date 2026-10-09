"""Outgoing messages. The rest of the app imports from here, never from a channel directly.

FRONT_DOOR=telegram uses app.telegram.send, anything else uses the Instagram senders.
"""
from app.config import settings

if settings.front_door == "telegram":
    from app.telegram.send import (  # noqa: F401
        send_cards, send_carousel, send_quick_replies, send_text, send_url_button,
    )
else:
    from app.meta.send import (  # noqa: F401
        send_cards, send_carousel, send_quick_replies, send_text, send_url_button,
    )
