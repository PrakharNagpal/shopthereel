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
