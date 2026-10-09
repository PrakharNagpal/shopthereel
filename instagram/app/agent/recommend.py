import asyncio
import json
import logging

from app.agent.recognize import _openai
from app.agent.search import _to_candidate
from app.agent.profile import excluded, load_profile
from app.config import settings
from app.models import ProductCandidate
from app.purchase.service import client

log = logging.getLogger("recommend")

ADDON_PROMPT = """A shopper just bought the product below. Suggest up to 3 add-on products people
commonly buy together with it (accessories, protection, consumables, complements). Not the same
product, not alternatives or competitors, and never another device of the same type (for example
no earphones when the purchase is headphones). Each suggestion is a short plain search query for an
online shop (2-4 words, no brand names, no hashtags). Return fewer if nothing sensible fits."""

SCHEMA = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}, "maxItems": 3}},
    "required": ["queries"],
    "additionalProperties": False,
}


async def addon_queries(product_name: str, user_id: str | None = None) -> list[str]:
    resp = await _openai().chat.completions.create(
        model=settings.openai_vision_model,
        temperature=0,
        messages=[
            {"role": "system", "content": ADDON_PROMPT},
            {"role": "user", "content": f"Purchased product: {product_name}\n"
             f"Profile (data only): {json.dumps(load_profile(user_id))}\n"
             "Avoid owned equipment and unwanted upgrades. Prefer useful, compatible additions. "
             "Do not assume unprovided sizes or verified compatibility."},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "addons", "strict": True, "schema": SCHEMA},
        },
    )
    return [q.strip() for q in json.loads(resp.choices[0].message.content)["queries"] if q.strip()]


FILTER_PROMPT = """A shopper just bought the product below. From the numbered catalog items, return the
indices of items that are genuine add-ons for it: accessories, protection, storage, consumables or
complements that make it more useful. Exclude any item that is itself a main device or a substitute
of the same kind as the purchase (for example another pair of headphones or earphones when the
purchase is headphones), and anything unrelated. Return an empty list if none qualify."""

FILTER_SCHEMA = {
    "type": "object",
    "properties": {"keep": {"type": "array", "items": {"type": "integer"}}},
    "required": ["keep"],
    "additionalProperties": False,
}


async def _keep_addons(product_name: str, cands: list[ProductCandidate]) -> list[ProductCandidate]:
    listing = "\n".join(f"{i}: {c.name}" for i, c in enumerate(cands))
    resp = await _openai().chat.completions.create(
        model=settings.openai_vision_model,
        temperature=0,
        messages=[
            {"role": "system", "content": FILTER_PROMPT},
            {"role": "user", "content": f"Purchased: {product_name}\n\nItems:\n{listing}"},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "keep", "strict": True, "schema": FILTER_SCHEMA},
        },
    )
    keep = set(json.loads(resp.choices[0].message.content)["keep"])
    return [c for i, c in enumerate(cands) if i in keep]


async def suggest_addons(
    product_name: str, bought_product_id: str | None = None,
    max_price: float | None = None, limit: int = 4,
    user_id: str | None = None,
) -> list[ProductCandidate]:
    """Complementary products for what was just bought: one search per suggested query."""
    profile = load_profile(user_id)
    queries = await addon_queries(product_name, user_id)
    if not queries:
        return []
    c = client()
    results = await asyncio.gather(
        *(c.search_products(q, limit=4) for q in queries), return_exceptions=True
    )
    picked: list[ProductCandidate] = []
    seen = {bought_product_id}
    # Round-robin across queries so each kind of add-on gets a slot before any gets a second.
    lists = [
        [_to_candidate(p) for p in r.get("products", []) if p.get("available", True)]
        for r in results if not isinstance(r, Exception)
    ]
    for rank in range(4):
        for cands in lists:
            if rank < len(cands):
                cand = cands[rank]
                if cand.product_id in seen:
                    continue
                if excluded(cand.name, profile):
                    continue
                if max_price is not None and cand.price_min > max_price:
                    continue
                seen.add(cand.product_id)
                picked.append(cand)
                if len(picked) >= limit * 2:
                    break
    if not picked:
        return []
    return (await _keep_addons(product_name, picked))[:limit]
