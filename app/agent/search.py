import logging

from app import state
from app.agent.recognize import recognize
from app.models import MediaBundle, ProductCandidate, RecognitionResult
from app.purchase.budget import get_budget
from app.purchase.service import client

log = logging.getLogger("agent")


def _to_candidate(p: dict) -> ProductCandidate:
    pr = p.get("priceRange") or {}
    lo, hi = pr.get("min") or {}, pr.get("max") or {}
    return ProductCandidate(
        product_id=p["id"],
        name=p["name"],
        merchant=(p.get("merchant") or {}).get("name", ""),
        image_url=p.get("imageUrl"),
        price_min=float(lo.get("amount", 0)),
        price_max=float(hi.get("amount", lo.get("amount", 0))),
        currency=lo.get("currency", ""),
        default_variant_id=(p.get("previewVariant") or {}).get("id"),
    )


async def search_cascade(
    queries: list[str], has_brand: bool, max_price: float | None = None
) -> tuple[str, str | None, list[ProductCandidate]]:
    """Try queries from specific to broad; stop at the first with results.

    Budget is applied client-side: the exact shape of Reap's price filter is unverified,
    and unaffordable items would only be refused later anyway.
    """
    c = client()
    for i, q in enumerate(queries):
        res = await c.search_products(q, limit=10)
        cands = [_to_candidate(p) for p in res.get("products", []) if p.get("available", True)]
        if max_price is not None:
            cands = [x for x in cands if x.price_min <= max_price]
        if cands:
            match = "exact" if i == 0 and has_brand else "similar"
            return match, q, cands[:3]
    return "none", None, []


async def recognize_and_search(bundle: MediaBundle, user_id: str | None = None) -> RecognitionResult:
    # Skip the cache when the user gave a hint, since the hint can change the target item.
    if not bundle.user_hint:
        cached = state.get_recognition(bundle.reel_id)
        if cached:
            return RecognitionResult.model_validate(cached)

    detected = await recognize(bundle)
    budget = get_budget(user_id) if user_id else None
    match, used, cands = await search_cascade(
        detected.queries, bool(detected.brand), budget[0] if budget else None
    )
    result = RecognitionResult(
        detected=detected, match_type=match, query_used=used, candidates=cands
    )
    if not bundle.user_hint:
        state.save_recognition(bundle.reel_id, result.model_dump())
    return result
