import httpx

from app.config import settings

# Endpoint per PLAN.md section 9. Verify path and version against the Meta docs
# for "Instagram API with Instagram Login" before relying on it.


def _url() -> str:
    return f"https://graph.instagram.com/{settings.graph_api_version}/me/messages"


async def _send(body: dict) -> None:
    headers = {"Authorization": f"Bearer {settings.ig_access_token}"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(_url(), json=body, headers=headers)
    if resp.status_code >= 400:
        # Error text from Meta does not contain our token.
        raise RuntimeError(f"Instagram send failed {resp.status_code}: {resp.text[:300]}")


async def send_text(igsid: str, text: str) -> None:
    await _send({"recipient": {"id": igsid}, "message": {"text": text}})


async def send_cards(igsid: str, candidates) -> None:
    """Generic-template carousel (max 10 cards) with a Buy button per product."""
    elements = []
    for c in candidates[:10]:
        price = f"{c.price_min:g}" if c.price_min == c.price_max else f"{c.price_min:g}-{c.price_max:g}"
        tail = f"{c.currency} {price}"
        head = f"{c.badge} | " if getattr(c, "badge", None) else ""
        room = 80 - len(head) - len(tail) - 3
        sub = f"{head}{c.merchant[:max(room, 0)].rstrip()} | {tail}"
        el = {
            "title": c.name[:80],
            "subtitle": sub[:80],
            "buttons": [{"type": "postback", "title": "Buy", "payload": f"BUY:{c.product_id}"}],
        }
        if c.image_url:
            el["image_url"] = c.image_url
        elements.append(el)
    await _send(
        {
            "recipient": {"id": igsid},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {"template_type": "generic", "elements": elements},
                }
            },
        }
    )


async def send_carousel(igsid: str, result) -> None:
    """RecognitionResult -> carousel."""
    await send_cards(igsid, result.candidates)


async def send_quick_replies(igsid: str, text: str, options: list[tuple[str, str]]) -> None:
    """options are (title, payload); Instagram allows up to 13, ~20 char titles."""
    await _send(
        {
            "recipient": {"id": igsid},
            "message": {
                "text": text,
                "quick_replies": [
                    {"content_type": "text", "title": t[:20], "payload": p}
                    for t, p in options[:13]
                ],
            },
        }
    )


async def send_url_button(igsid: str, text: str, title: str, url: str) -> None:
    await _send(
        {
            "recipient": {"id": igsid},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": [
                            {
                                "title": text[:80],
                                "buttons": [{"type": "web_url", "url": url, "title": title[:20]}],
                            }
                        ],
                    },
                }
            },
        }
    )
