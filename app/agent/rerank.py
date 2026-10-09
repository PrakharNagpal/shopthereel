import json
import logging

from app.agent.recognize import _openai
from app.config import settings
from app.models import ProductCandidate

log = logging.getLogger("rerank")

RERANK_PROMPT = """You compare a product seen in a social media video against catalog items.
The first image is the reference frame from the video. Then come the catalog items, each introduced
by its index and name. Most reels show no brand, so judge by how the product LOOKS: product type,
shape, silhouette, colour, material, style, key design details. Ignore the price and the brand name.
Give each item a score from 0 to 1: 1 means it looks like the same or a near-identical product,
0.5 means the same type with a loosely similar look, 0 means a different kind of product or form
factor (for example earbuds versus over-ear headphones).
Use the whole range and avoid ties: items of the same type must be separated by how closely their
colour, shape, size, proportions and style match the reference. A different colour or a clearly
different style should lower the score noticeably. Compare the items with each other before scoring.
Return a score for every index."""

SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"index": {"type": "integer"}, "score": {"type": "number"}},
                "required": ["index", "score"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["scores"],
    "additionalProperties": False,
}


async def rerank(
    frame_b64: str, description: str, cands: list[ProductCandidate]
) -> list[tuple[ProductCandidate, float]]:
    """Score candidates by visual similarity to the reel frame. Falls back to search order."""
    withimg = [c for c in cands if c.image_url]
    if not withimg or not frame_b64:
        return [(c, 0.5) for c in cands]
    content: list[dict] = [
        {"type": "text", "text": f"Reference product (from the video): {description}"},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}", "detail": "low"}},
    ]
    for i, c in enumerate(withimg):
        content.append({"type": "text", "text": f"Item {i}: {c.name}"})
        content.append({"type": "image_url", "image_url": {"url": c.image_url, "detail": "low"}})
    try:
        resp = await _openai().chat.completions.create(
            model=settings.openai_vision_model,
            temperature=0,
            messages=[
                {"role": "system", "content": RERANK_PROMPT},
                {"role": "user", "content": content},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "scores", "strict": True, "schema": SCHEMA},
            },
        )
        scores = {s["index"]: s["score"] for s in json.loads(resp.choices[0].message.content)["scores"]}
    except Exception:
        log.exception("rerank failed, keeping search order")  # e.g. unreachable image URL
        return [(c, 0.5) for c in cands]
    scored = [(c, float(scores.get(i, 0.0))) for i, c in enumerate(withimg)]
    return sorted(scored, key=lambda x: x[1], reverse=True)
