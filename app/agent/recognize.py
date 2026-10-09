import asyncio

from openai import AsyncOpenAI

from app.agent.prompts import DETECTED_PRODUCT_SCHEMA, SYSTEM_PROMPT
from app.config import settings
from app.models import DetectedProduct, MediaBundle

_client: AsyncOpenAI | None = None


def _openai() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=45)
    return _client


def _user_content(bundle: MediaBundle) -> list[dict]:
    text = (
        f"Caption: {bundle.caption or '(none)'}\n"
        f"Transcript: {bundle.transcript or '(none)'}\n"
        f"User hint: {bundle.user_hint or '(none)'}\n"
        f"There are {len(bundle.frames_b64)} frames, indexed from 0."
    )
    parts: list[dict] = [{"type": "text", "text": text}]
    for b64 in bundle.frames_b64[:8]:
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"},
            }
        )
    return parts


async def recognize(bundle: MediaBundle) -> DetectedProduct:
    """One vision call with strict structured output. One retry on timeout."""
    kwargs = dict(
        model=settings.openai_vision_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_content(bundle)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "detected_product",
                "strict": True,
                "schema": DETECTED_PRODUCT_SCHEMA,
            },
        },
    )
    for attempt in range(2):
        try:
            resp = await _openai().chat.completions.create(**kwargs)
            break
        except (asyncio.TimeoutError, TimeoutError):
            if attempt == 1:
                raise
        except Exception as e:  # openai.APITimeoutError subclasses Exception
            if "Timeout" in type(e).__name__ and attempt == 0:
                continue
            raise
    detected = DetectedProduct.model_validate_json(resp.choices[0].message.content)
    # Keep best_frame inside the frames we actually sent.
    if bundle.frames_b64:
        detected.best_frame = min(max(detected.best_frame, 0), len(bundle.frames_b64) - 1)
    return detected
