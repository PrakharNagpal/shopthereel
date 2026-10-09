import asyncio
import logging
import re

from app import state
from app.agent.recognize import recognize
from app.agent.rerank import rerank
from app.models import DetectedProduct, MediaBundle, ProductCandidate, RecognitionResult
from app.purchase.budget import get_budget
from app.purchase.service import client

log = logging.getLogger("agent")

MIN_SCORE = 0.35  # below this a candidate is a different kind of product
MAX_RESULTS = 8   # carousel cards shown; Instagram allows up to 10


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


def assign_badges(scored: list[tuple[ProductCandidate, float]]) -> None:
    """Label up to three cards: Best match (top score), Best value, Cheapest close match."""
    if not scored:
        return
    top, top_score = scored[0]
    top.badge = "Best match"
    close = [(c, sc) for c, sc in scored[1:] if sc >= max(top_score - 0.3, MIN_SCORE)]
    # Best value: strongest score per dollar among close matches that cost less than the top pick.
    cheaper = [(c, sc) for c, sc in close if c.price_min < top.price_min]
    if cheaper:
        value, _ = max(cheaper, key=lambda x: x[1] / max(x[0].price_min, 1))
        value.badge = "Best value"
    # Cheapest close match: only if it is not the top pick and not already labelled.
    cheapest = min([(top, top_score)] + close, key=lambda x: x[0].price_min)[0]
    if cheapest is not top and not cheapest.badge:
        cheapest.badge = "Cheapest close match"


async def gather_candidates(queries: list[str]) -> list[tuple[int, ProductCandidate]]:
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
    seen_listings: set[tuple[str, str, float]] = set()  # the catalog sometimes lists a product twice
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            log.warning("query %d failed: %s", i, res)
            continue
        for p in res.get("products", []):
            if not p.get("available", True) or p["id"] in pooled:
                continue
            cand = _to_candidate(p)
            listing = (cand.name.lower(), cand.merchant.lower(), cand.price_min)
            if listing in seen_listings:
                continue
            seen_listings.add(listing)
            pooled[p["id"]] = (i, cand)
    return list(pooled.values())


def _apply_budget(
    ranked: list[tuple[ProductCandidate, float]], budget: tuple[float, str] | None
) -> tuple[list[tuple[ProductCandidate, float]], str | None]:
    """Keep what fits the budget; explain when the closest look-alike does not."""
    if not budget or not ranked:
        return ranked, None
    limit, cur = budget
    best = ranked[0][0]
    affordable = [(c, sc) for c, sc in ranked if c.price_min <= limit]
    note = None
    if best.price_min > limit and affordable:
        note = (
            f"The closest match ({best.name[:50]}) is {cur} {best.price_min:g}, over your "
            f"{cur} {limit:g} limit. Here are the best ones within budget."
        )
    return affordable, note


async def recognize_and_search(bundle: MediaBundle, user_id: str | None = None) -> RecognitionResult:
    """Recognise, search, rank visually. The cache holds the budget-independent ranking;
    each user's budget, badges and note are applied fresh on every call."""
    cached = None if bundle.user_hint else state.get_recognition(bundle.reel_id)
    if cached and "ranked" in cached:
        detected = DetectedProduct.model_validate(cached["detected"])
        ranked = [(ProductCandidate.model_validate(r["c"]), r["s"]) for r in cached["ranked"]]
        first_query = {k: v for k, v in cached["first_query"].items()}
    else:
        detected = await recognize(bundle)
        pooled = await gather_candidates(detected.queries)
        first_query = {c.product_id: i for i, c in pooled}
        frame = bundle.frames_b64[detected.best_frame] if bundle.frames_b64 else ""
        desc = f"{detected.name}; " + ", ".join(detected.attributes)
        ranked = [(c, sc) for c, sc in await rerank(frame, desc, [c for _, c in pooled]) if sc >= MIN_SCORE]
        if not bundle.user_hint:
            state.save_recognition(bundle.reel_id, {
                "detected": detected.model_dump(),
                "ranked": [{"c": c.model_dump(), "s": sc} for c, sc in ranked],
                "first_query": first_query,
            })

    ranked, note = _apply_budget(ranked, get_budget(user_id) if user_id else None)
    ranked = ranked[:MAX_RESULTS]
    assign_badges(ranked)
    tokens = _model_tokens(detected.name)
    top = [c for c, _ in ranked]
    exact = [c for c in top if _verified(c, detected.brand, tokens)]
    if not top:
        match, used, final = "none", None, []
    elif exact:
        match, final = "exact", exact + [c for c in top if c not in exact]
        used = detected.queries[first_query.get(exact[0].product_id, 0)]
    else:
        match, final = "similar", top
        used = detected.queries[first_query.get(top[0].product_id, 0)]
    return RecognitionResult(
        detected=detected, match_type=match, query_used=used, candidates=final, note=note
    )
