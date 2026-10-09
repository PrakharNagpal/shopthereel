"""Phase 1 proof: one purchase end to end against the Reap sandbox.

Run from repo root:
  python -m scripts.reap_e2e --query "wireless headphones"                 # creates enrollment first
  python -m scripts.reap_e2e --query "wireless headphones" --enrollment-id <id>

Response field names beyond those in PLAN.md are unverified. The script prints
the top-level keys of each response so you can adjust the .get() paths below.
"""
import argparse
import asyncio
import json
import sys
import webbrowser

from app.config import settings
from app.reap.client import ReapClient, ReapError

TERMINAL = {"COMPLETED", "FAILED", "CANCELED", "CANCELLED", "EXPIRED"}


def show(step: str, data) -> None:
    keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
    print(f"[{step}] keys: {keys}")


def first(data: dict, *names):
    """Return the first list found under any of the given keys (also under 'data')."""
    for src in (data, data.get("data", {}) if isinstance(data.get("data"), dict) else {}):
        for n in names:
            if isinstance(src.get(n), list):
                return src[n]
    if isinstance(data.get("data"), list):
        return data["data"]
    return []


async def ensure_enrollment(c: ReapClient, enrollment_id: str | None) -> str:
    if enrollment_id:
        return enrollment_id
    enr = await c.create_enrollment("e2e-prakhar")
    show("enrollment", enr)
    eid = enr.get("id") or enr.get("data", {}).get("id")
    url = enr.get("url") or enr.get("nextAction", {}).get("url") or enr.get("hostedUrl")
    print(f"enrollment id: {eid}\nopen and enter sandbox card + OTP: {url}")
    if url:
        webbrowser.open(url)
    for _ in range(90):
        cur = await c.get_enrollment(eid)
        status = cur.get("status") or cur.get("data", {}).get("status")
        print(f"  enrollment status: {status}")
        if status == "ACTIVE":
            return eid
        await asyncio.sleep(2)
    sys.exit("enrollment never became ACTIVE")


async def main(query: str, enrollment_id: str | None) -> None:
    c = ReapClient()
    try:
        eid = await ensure_enrollment(c, enrollment_id)

        res = await c.search_products(query)
        show("search", res)
        products = first(res, "products", "items", "results")
        if not products:
            sys.exit(f"no products for {query!r}; raw: {json.dumps(res)[:400]}")
        pid = products[0].get("id") or products[0].get("productId")
        print(f"picked product {pid}: {products[0].get('name') or products[0].get('title')}")

        det = await c.product_details([pid])
        show("details", det)
        items = first(det, "products", "items", "results")
        prod = items[0] if items else det.get("data", det)
        options = prod.get("options") or []
        if options:
            # Naive pick: first available value of each option group.
            opt_ids = []
            for g in options:
                vals = g.get("values") or []
                avail = [v for v in vals if v.get("available", True)]
                if avail:
                    opt_ids.append(avail[0].get("optionId"))
            var = await c.resolve_variant(pid, opt_ids)
            show("variant", var)
            variant_id = var.get("id") or var.get("variant", {}).get("id")
        else:
            variant_id = (prod.get("defaultVariant") or {}).get("id")
        print(f"variant id: {variant_id}")

        body = {
            "items": [{"variantId": variant_id, "quantity": 1}],
            "email": settings.demo_email,
            "shippingAddress": json.loads(settings.demo_shipping_json),
        }
        quote = await c.create_quote(body)
        show("quote", quote)
        qid = quote.get("id") or quote.get("data", {}).get("id")
        print(f"quote id: {qid}")
        # Optional: pick cheapest shipping via c.set_shipping_option once the
        # quote response shape for shipping options is confirmed.

        co = await c.create_checkout(qid, eid, settings.reap_return_url)
        show("checkout", co)
        cid = co.get("id") or co.get("data", {}).get("id")
        url = (co.get("nextAction") or {}).get("url")
        if url:
            print(f"approve here: {url}")
            webbrowser.open(url)

        for _ in range(30):
            cur = await c.get_checkout(cid)
            status = cur.get("status")
            print(f"  checkout status: {status}")
            if status in TERMINAL:
                print(f"orderId={cur.get('orderId')} finalAmount={cur.get('finalAmount')}")
                return
            await asyncio.sleep(2)
        sys.exit("checkout did not reach a terminal status in 60 s")
    except ReapError as e:
        sys.exit(f"Reap error: {e}")
    finally:
        await c.aclose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--enrollment-id")
    a = ap.parse_args()
    asyncio.run(main(a.query, a.enrollment_id))
