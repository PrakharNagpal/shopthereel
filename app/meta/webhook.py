import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.config import settings

router = APIRouter()
log = logging.getLogger("webhook")


def valid_signature(raw_body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256=") or not settings.meta_app_secret:
        return False
    expected = hmac.new(
        settings.meta_app_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@router.get("/webhook", response_class=PlainTextResponse)
async def verify(request: Request) -> str:
    q = request.query_params
    if (
        q.get("hub.mode") == "subscribe"
        and settings.meta_verify_token
        and q.get("hub.verify_token") == settings.meta_verify_token
    ):
        return q.get("hub.challenge", "")
    raise HTTPException(status_code=403)


async def handle_payload(payload: dict) -> None:
    # Raw body may contain user ids and message text; this is dev-only logging.
    log.info("webhook body: %s", json.dumps(payload))
    from app.dm.router import handle_payload as route  # late import avoids a cycle

    await route(payload)


@router.post("/webhook")
async def receive(request: Request, background: BackgroundTasks) -> dict:
    raw = await request.body()
    if not valid_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=403)
    try:
        payload = json.loads(raw)
    except ValueError:
        return {"ok": True}  # never crash on junk
    background.add_task(handle_payload, payload)
    return {"ok": True}
