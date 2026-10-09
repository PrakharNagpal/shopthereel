You are helping a 2-person team build ShopTheReel at a 5-hour hackathon. Read PLAN.md first.

Lanes:
- Reap lane (Prakhar): app/reap/, app/agent/, app/purchase/, scripts/reap_e2e.py, scripts/recognize_local.py
- Meta lane (Pratham): app/meta/, app/media/, app/dm/, scripts/media_local.py, scripts/send_test_dm.py
- Shared (change only when explicitly asked): app/models.py, app/state.py, app/main.py, app/config.py
Only edit files in the lane you are asked to work in.

Hard rules:
1. Python 3.11, FastAPI, httpx (async), pydantic v2, sqlite3. No new frameworks.
2. Code against the contracts in app/models.py. Never change a shared model silently.
3. Secrets only from environment via app/config.py. Never hardcode, print or log API keys,
   tokens, card numbers, CVVs, OTPs, emails or full addresses.
4. Card details must never be sent to OpenAI or any model, stored, or logged. Card entry
   happens only on Reap's hosted page.
5. Never scrape merchant websites or checkout pages. All product data and purchases go
   through Reap Agentic endpoints.
6. Reap: always send Authorization, Reap-Version, Idempotency-Key (on creating POSTs).
   Add X-Simulate-Checkout: COMPLETED on checkout when REAP_SIMULATE_CHECKOUT=true.
7. Meta webhook must return 200 fast; do heavy work in background tasks. Verify
   X-Hub-Signature-256. Ignore echo messages. Dedupe by message mid.
8. Every external call has a timeout and a user-friendly failure message in the DM.
9. Keep functions small and typed. Prefer simple over clever. No premature abstraction.
10. After writing code, give the exact command to run/test it.
11. Do not use em dashes in any user-facing strings or docs.

When unsure about an external API field name, say so and point to where to verify it,
rather than inventing it.
