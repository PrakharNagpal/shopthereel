from typing import Literal, Optional

from pydantic import BaseModel


class InboundEvent(BaseModel):
    igsid: str
    kind: Literal["reel", "text", "postback", "quick_reply"]
    mid: Optional[str] = None
    reel_url: Optional[str] = None
    reel_title: Optional[str] = None
    reel_id: Optional[str] = None
    text: Optional[str] = None
    payload: Optional[str] = None


REEL_TYPES = {"ig_reel", "reel", "video", "share", "ig_post"}


def parse_events(body: dict) -> list[InboundEvent]:
    """Webhook JSON -> events. Unknown shapes are skipped, never raised.

    Attachment key names (payload.url, title, reel_video_id) follow PLAN.md section 9 and
    must be confirmed against docs/sample_ig_reel_webhook.json once a real reel arrives.
    """
    events: list[InboundEvent] = []
    for entry in body.get("entry") or []:
        for m in entry.get("messaging") or []:
            ev = _parse_one(m)
            if ev:
                events.append(ev)
    return events


def _parse_one(m: dict) -> Optional[InboundEvent]:
    sender = (m.get("sender") or {}).get("id")
    if not sender:
        return None
    if "postback" in m:
        return InboundEvent(
            igsid=sender,
            kind="postback",
            mid=(m["postback"] or {}).get("mid"),
            payload=(m["postback"] or {}).get("payload"),
        )
    msg = m.get("message")
    if not msg or msg.get("is_echo"):
        return None  # reads, reactions, our own messages
    mid = msg.get("mid")
    qr = msg.get("quick_reply")
    if qr:
        return InboundEvent(
            igsid=sender, kind="quick_reply", mid=mid, payload=qr.get("payload"), text=msg.get("text")
        )
    for att in msg.get("attachments") or []:
        if att.get("type") in REEL_TYPES:
            p = att.get("payload") or {}
            return InboundEvent(
                igsid=sender,
                kind="reel",
                mid=mid,
                reel_url=p.get("url"),
                reel_title=p.get("title"),
                reel_id=str(p.get("reel_video_id") or p.get("id") or mid or ""),
            )
    if msg.get("text"):
        return InboundEvent(igsid=sender, kind="text", mid=mid, text=msg["text"])
    return None
