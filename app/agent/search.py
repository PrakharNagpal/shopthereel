import asyncio
import logging
import re

from app import state
from app.agent.recognize import recognize
from app.agent.rerank import rerank
from app.models import MediaBundle, ProductCandidate, RecognitionResult
from app.purchase.budget import get_budget
from app.purchase.service import client

log = logging.getLogger("agent")

MIN_SCORE = 0.35  # below this a candidate is a different kind of product


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


def _model_tokens(name: str) -> list[str]:
    """Tokens that look like model numbers (contain a digit), e.g. J236, WH-1000XM5."""
    return [t.lower() for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{2,}", name) if any(c.isdigit() for c in t)]


def _verified(c: ProductCandidate, brand: str | None, model_tokens: list[str]) -> bool:
    """A candidate counts as the exact product only if its name has the brand or a model number."""
    name = c.name.lower()
    return bool((brand and brand.lower() in name) or any(t in name for t in model_tokens))


async def gather_candidates(
    queries: list[str], max_price: float | None = None
) -> list[tuple[int, ProductCandidate]]:
    """Search every query concurrently and pool the results (deduped), tagged by query index."""
    c = client()
    results = list(await asyncio.gather(
        *(c.search_products(q, limit=8) for q in queries), return_exceptions=True
    ))
    # The sandbox 503s in bursts: give each failed query one more try after a pause.
    failed = [i for i, r in enumerate(results) if isinstance(r, Exception)]
    if failed:
        await asyncio.sleep(3)
        again = await asyncio.gather(
            *(c.search_products(queries[i], limit=8) for i in failed), return_exceptions=True
        )
        for i, r in zip(failed, again):
            results[i] = r
    pooled: dict[str, tuple[int, ProductCandidate]] = {}
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            log.warning("query %d failed: %s", i, res)
            continue
        for p in res.get("products", []):
            if not p.get("available", True) or p["id"] in pooled:
                continue
            cand = _to_candidate(p)
            if max_price is None or cand.price_min <= max_price:
                pooled[p["id"]] = (i, cand)
    return list(pooled.values())


async def recognize_and_search(bundle: MediaBundle, user_id: str | None = None) -> RecognitionResult:
    # Skip the cache when the user gave a hint, since the hint can change the target item.
    if not bundle.user_hint:
        cached = state.get_recognition(bundle.reel_id)
        if cached:
            return RecognitionResult.model_validate(cached)

    detected = await recognize(bundle)
    budget = get_budget(user_id) if user_id else None
    pooled = await gather_candidates(detected.queries, budget[0] if budget else None)
    cands = [c for _, c in pooled]
    first_query = {c.product_id: i for i, c in pooled}

    frame = bundle.frames_b64[detected.best_frame] if bundle.frames_b64 else ""
    desc = f"{detected.name}; " + ", ".join(detected.attributes)
    ranked = await rerank(frame, desc, cands)

    tokens = _model_tokens(detected.name)
    verified = [c for c, _ in ranked if _verified(c, detected.brand, tokens)]
    top = [c for c, score in ranked if score >= MIN_SCORE][:3]
    # "exact" is earned: a candidate carries the detected brand or model number.
    exact = [c for c in verified if c in top] or [c for c in verified[:1] if ranked and ranked[0][0] == c]
    if not top:
        match, used, final = "none", None, []
    elif exact:
        match, final = "exact", exact + [c for c in top if c not in exact]
        used = detected.queries[first_query[exact[0].product_id]]
        final = final[:3]
    else:
        match, final = "similar", top
        used = detected.queries[first_query[top[0].product_id]]
    result = RecognitionResult(
        detected=detected, match_type=match, query_used=used, candidates=final
    )
    if not bundle.user_hint:
        state.save_recognition(bundle.reel_id, result.model_dump())
    return result
