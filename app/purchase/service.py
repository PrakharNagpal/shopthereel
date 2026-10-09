import asyncio
import json
import logging
from typing import Optional

from app import state
from app.config import settings
from app.models import OrderResult, QuoteSummary, VariantOption
from app.purchase.budget import check_budget
from app.reap.client import ReapClient, ReapError

log = logging.getLogger("purchase")

TERMINAL = {"COMPLETED", "FAILED", "CANCELED", "CANCELLED", "EXPIRED"}
_client: Optional[ReapClient] = None


def client() -> ReapClient:
    global _client
    if _client is None:
        _client = ReapClient()
    return _client


def _money(v) -> float:
    """Reap money is {'amount': n, 'currency': c}; tax is nested one level deeper."""
    while isinstance(v, dict) and "amount" in v:
        v = v["amount"]
    return float(v or 0)


# ---------- enrollment ----------

async def ensure_enrollment(user_id: str) -> str | None:
    """Returns hosted card-entry URL if user not enrolled, else None."""
    c = client()
    eid = state.get_user(user_id).get("enrollment_id")
    if eid:
        cur = await c.get_enrollment(eid)
        if cur.get("status") == "ACTIVE":
            return None
        url = _enrollment_url(cur)
        if url:
            return url
    enr = await c.create_enrollment()
    state.update_user(user_id, enrollment_id=enr.get("id"))
    # Hosted URL field name is unverified; check the first real response.
    url = _enrollment_url(enr)
    if not url:
        log.error("enrollment response had no URL; keys=%s", list(enr))
        raise ReapError("NO_ENROLLMENT_URL", "no hosted URL in enrollment response", 0)
    return url


def _enrollment_url(enr: dict) -> Optional[str]:
    return (
        (enr.get("nextAction") or {}).get("url")
        or enr.get("url")
        or enr.get("hostedUrl")
        or enr.get("enrollmentUrl")
    )


# ---------- options / variant ----------

async def get_options(product_id: str) -> list[VariantOption]:
    det = await client().product_details([product_id])
    prods = det.get("products") or []
    if not prods:
        return []
    out: list[VariantOption] = []
    for group in prods[0].get("options") or []:
        for v in group.get("values") or []:
            out.append(
                VariantOption(
                    group=group["name"],
                    label=v["label"],
                    option_id=v["optionId"],
                    available=bool(v.get("available", True)),
                )
            )
    return out


async def resolve_variant(product_id: str, option_ids: list[str]) -> str:
    c = client()
    if not option_ids:
        det = await c.product_details([product_id])
        return det["products"][0]["defaultVariant"]["id"]
    res = await c.resolve_variant(product_id, option_ids)
    # Response shape unverified: accept {'id'} or {'variant': {'id'}}.
    return res.get("id") or res["variant"]["id"]


# ---------- quote ----------

async def create_quote(user_id: str, variant_id: str) -> QuoteSummary:
    c = client()
    body = {
        "items": [{"variantId": variant_id, "quantity": 1}],
        "email": settings.demo_email,
        "shippingAddress": json.loads(settings.demo_shipping_json),
    }
    q = await c.create_quote(body)

    # Pick cheapest shipping option if the default selection is not it.
    opts = q.get("shippingOptions") or []
    if len(opts) > 1:
        cheapest = min(opts, key=lambda o: _money(o["price"]))
        if not cheapest.get("selected"):
            # Request body shape unverified: check Reap docs for shipping-option.
            q = await c.set_shipping_option(q["id"], {"shippingOptionId": cheapest["id"]})

    ab = q["amountBreakdown"]
    final = _money(ab["finalAmount"])
    currency = (ab["finalAmount"] or {}).get("currency") or settings.reap_default_currency
    ok, msg = check_budget(user_id, final, currency)
    state.update_user(user_id, pending_variant_id=variant_id, pending_quote_id=q["id"])
    return QuoteSummary(
        quote_id=q["id"],
        items_subtotal=_money(ab["itemsSubtotal"]),
        shipping=_money(ab["shipping"]),
        tax=_money(ab["tax"]),
        final_amount=final,
        currency=currency,
        expires_at=q.get("expiresAt", ""),
        within_budget=ok,
        budget_message=msg,
    )


# ---------- checkout ----------

def _to_order(co: dict) -> OrderResult:
    fa = co.get("finalAmount")
    return OrderResult(
        checkout_id=co["id"],
        status=co.get("status", "UNKNOWN"),
        approval_url=(co.get("nextAction") or {}).get("url"),
        order_id=co.get("orderId"),
        final_amount=_money(fa) if fa is not None else None,
        currency=fa.get("currency") if isinstance(fa, dict) else None,
    )


async def start_checkout(user_id: str, quote_id: str) -> OrderResult:
    """Only runs for the quote this user last saw, and only after an explicit CONFIRM."""
    u = state.get_user(user_id)
    if u.get("pending_quote_id") != quote_id:
        raise ReapError("STALE_QUOTE", "quote does not match this user's pending quote", 0)
    if not u.get("enrollment_id"):
        raise ReapError("NOT_ENROLLED", "no card enrolled", 0)
    c = client()
    try:
        co = await c.create_checkout(quote_id, u["enrollment_id"], settings.reap_return_url)
    except ReapError as e:
        # Re-quote once when the quote expired, then retry with the fresh one.
        if e.code in ("QUOTE_EXPIRED", "QUOTE_UNFULFILLABLE") and u.get("pending_variant_id"):
            fresh = await create_quote(user_id, u["pending_variant_id"])
            if not fresh.within_budget:
                raise ReapError("OVER_BUDGET", fresh.budget_message or "", 0)
            co = await c.create_checkout(
                fresh.quote_id, u["enrollment_id"], settings.reap_return_url
            )
        else:
            raise
    order = _to_order(co)
    state.update_user(user_id, pending_checkout_id=order.checkout_id)
    return order


async def poll_checkout(checkout_id: str) -> OrderResult:
    return _to_order(await client().get_checkout(checkout_id))


async def watch_checkout(igsid: str, checkout_id: str, timeout_s: int = 120) -> None:
    """Background poller: DMs the outcome. Run with asyncio.create_task / BackgroundTasks."""
    from app.meta.send import send_text

    waited = 0
    while waited < timeout_s:
        try:
            order = await poll_checkout(checkout_id)
        except ReapError as e:
            log.warning("poll error %s", e.code)
            order = None
        if order and order.status in TERMINAL:
            if order.status == "COMPLETED":
                state.save_order(
                    checkout_id, igsid, order.order_id, order.final_amount, order.currency
                )
                state.update_user(igsid, pending_checkout_id=None, pending_quote_id=None)
                await send_text(
                    igsid,
                    f"Ordered! Order #{order.order_id}, "
                    f"{order.currency} {order.final_amount} charged.",
                )
            else:
                await send_text(
                    igsid, "The payment did not go through, so nothing was charged. Try again?"
                )
            return
        await asyncio.sleep(2)
        waited += 2
    await send_text(igsid, "I did not see the payment finish. If you approved it, check your email.")


def friendly_error(e: ReapError) -> str:
    if e.code == "CARD_PAYMENT_UNAVAILABLE":
        return "This merchant cannot take your card right now. Try another product."
    if e.code == "QUOTE_UNFULFILLABLE":
        return "That item cannot be delivered right now. Try another one."
    if e.code == "OVER_BUDGET":
        return e.message
    if e.code in ("STALE_QUOTE", "NOT_ENROLLED"):
        return "That offer is out of date. Tap Buy on the product again."
    return "Something went wrong talking to the store. Please try again in a moment."
