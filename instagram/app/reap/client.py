import asyncio
import uuid
from typing import Any, Optional

import httpx

from app.config import settings


class ReapError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(f"{status} {code}: {message}")
        self.code = code
        self.message = message
        self.status = status


class ReapClient:
    """Thin async wrapper over the Reap Agentic API."""

    def __init__(self) -> None:
        headers = {
            "Authorization": f"Bearer {settings.reap_api_key}",
            "Reap-Version": settings.reap_version,
            "Content-Type": "application/json",
        }
        self._http = httpx.AsyncClient(
            base_url=settings.reap_base_url, headers=headers, timeout=30
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict] = None,
        idempotent: bool = False,
        extra_headers: Optional[dict] = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = dict(extra_headers or {})
        if idempotent:
            headers["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())
        for attempt in range(5):
            resp = await self._http.request(method, path, json=json, headers=headers)
            # Sandbox returns transient 502/503; same idempotency key makes retry safe.
            if resp.status_code in (502, 503) and attempt < 4:
                await asyncio.sleep(1.0 * (attempt + 1))
                continue
            break
        if resp.status_code >= 400:
            raise self._to_error(resp)
        return resp.json() if resp.content else {}

    @staticmethod
    def _to_error(resp: httpx.Response) -> ReapError:
        # Error body shape is unverified: check Reap docs and adjust the keys below.
        try:
            body = resp.json()
        except ValueError:
            return ReapError("UNKNOWN", resp.text[:200], resp.status_code)
        err = body.get("error", body) if isinstance(body, dict) else {}
        msg = str(err.get("message", ""))
        # Field paths and validation reasons help debugging; they contain no user data.
        for d in (err.get("detail") or {}).get("errors", []):
            msg += f" [{d.get('path')}: {d.get('message')}]"
        return ReapError(str(err.get("code", "UNKNOWN")), msg[:300], resp.status_code)

    async def get(self, path: str) -> Any:
        return await self._request("GET", path)

    async def post(self, path: str, json: dict, extra_headers: Optional[dict] = None) -> Any:
        return await self._request(
            "POST", path, json=json, idempotent=True, extra_headers=extra_headers
        )

    # ---- Agentic endpoints (paths from PLAN.md phase 1) ----

    async def create_enrollment(self, owner_id: str) -> Any:
        body = {
            "source": "EXTERNAL",
            "owner": {"type": "CLIENT_REFERENCE", "id": owner_id, "email": settings.demo_email},
            "presentation": {"type": "REDIRECT", "returnUrl": settings.reap_return_url},
        }
        return await self.post("/agentic/enrollments", body)

    async def get_enrollment(self, enrollment_id: str) -> Any:
        return await self.get(f"/agentic/enrollments/{enrollment_id}")

    async def search_products(
        self, query: str, limit: int = 5, max_price: Optional[float] = None
    ) -> Any:
        body: dict = {
            "query": query,
            "context": {
                "country": settings.reap_default_country,
                "currency": settings.reap_default_currency,
            },
            "filters": {"availability": "AVAILABLE_ONLY"},
            "pagination": {"limit": limit},
        }
        if max_price is not None:
            body["filters"]["price"] = {"max": max_price}  # field shape unverified
        return await self.post("/agentic/products/search", body)

    async def product_details(self, product_ids: list[str]) -> Any:
        return await self.post("/agentic/products/details", {"productIds": product_ids})

    async def resolve_variant(self, product_id: str, option_ids: list[str]) -> Any:
        return await self.post(
            "/agentic/products/variant", {"productId": product_id, "optionIds": option_ids}
        )

    async def create_quote(self, body: dict) -> Any:
        return await self.post("/agentic/quotes", body)

    async def set_shipping_option(self, quote_id: str, body: dict) -> Any:
        return await self.post(f"/agentic/quotes/{quote_id}/shipping-option", body)

    async def create_checkout(self, quote_id: str, enrollment_id: str, return_url: str, idempotency_key: str | None = None) -> Any:
        extra = (
            {"X-Simulate-Checkout": "COMPLETED"} if settings.reap_simulate_checkout else None
        )
        body = {
            "quoteId": quote_id,
            "enrollmentId": enrollment_id,
            "presentation": {"type": "REDIRECT", "returnUrl": return_url},
        }
        return await self._request("POST", "/agentic/checkouts", json=body, idempotent=True, extra_headers=extra, idempotency_key=idempotency_key)

    async def get_checkout(self, checkout_id: str) -> Any:
        return await self.get(f"/agentic/checkouts/{checkout_id}")
