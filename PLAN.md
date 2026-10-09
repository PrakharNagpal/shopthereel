# ShopTheReel | Build Plan

Reap × 65labs Agentic Buildathon | Friday 9 October 2026 | SQ Collective, Singapore

> **One line:** Share an Instagram reel to our bot in Instagram DMs. An OpenAI-powered agent recognises the product, finds it (or close matches) through Reap's merchant catalog, quotes it, enforces the user's budget, and completes the purchase only after the user approves the charge on a Reap-hosted page. The AI never sees the card.

This file is the single source of truth for the team and for the coding agents (Codex, Claude). Keep it in the repo root. Agents: read the whole file before writing code, follow the **Rules for coding agents** section, and only work inside your assigned lane unless told otherwise.

---

## 0. Hard deadlines and rules

| Time (SGT) | What |
|---|---|
| 3:45 pm | Start building |
| **4:30 pm** | Team must be registered (2 people) to get the Reap sandbox key. Late = no key |
| 7:00 pm | Dinner (eat while something runs) |
| 8:00 pm | **Feature freeze.** Only bug fixes, README, demo video after this |
| 8:45 pm | Last code push |
| **9:00 pm** | **Submission closes. Sharp.** |
| 9:00-10:00 pm | Optional live demos |

Event rules we must respect:

- Must use Reap's Agentic module (we do). Kwal is optional.
- Checkout is simulated. No real purchases, nothing ships.
- **Never** bypass Agentic by scraping merchant checkout.
- **Never** pass raw card details to an AI model, log them, or commit them.
- Never paste API keys or card details in the event group chat.
- Sandbox card: replace every `x` in the card number with `4`; pad CVV to 3 digits with leading zeros (7 → 007, 47 → 047); OTP is the shared sandbox OTP from the event message.

---

## 1. Team and lanes

| | **Prakhar | Reap lane** | **Pratham | Meta lane** |
|---|---|---|
| Owns | Reap client, purchase flow, budget guard, OpenAI recognition + search cascade (the "agent brain") | Instagram account + Meta app, webhook, media pipeline (download, frames, transcript), all DM rendering and button handling |
| Main folders | `app/reap/`, `app/agent/`, `app/purchase/` | `app/meta/`, `app/media/`, `app/dm/` |
| Shared | `app/models.py`, `app/state.py`, `app/main.py`, `.env.example` | same |
| First blocker to clear | Reap key + `ACTIVE` enrollment | Meta app in dev mode + webhook verified + tester accounts accepted |

**Why this split:** Meta setup has the longest unpredictable wait (tokens, permissions, tester invites), so the Meta lane also owns the media pipeline, which can be built and tested on local files while Meta setup is pending. The Reap lane owns everything after "here are frames + caption + transcript", so the two halves meet at one clean interface (section 4).

**Sync points** (5 minutes each, in person):

1. **4:15 pm** | Contracts check: both agree on `app/models.py` (section 4). Commit it before anyone builds on it.
2. **5:30 pm** | Reap lane demos `scripts/reap_e2e.py` printing an order ID. Meta lane demos webhook receiving a test DM.
3. **6:45 pm** | Integration: real reel in DM → product cards out.
4. **7:45 pm** | Full flow on phone, decide what to cut.
5. **8:30 pm** | Record demo, submit.

---

## 2. Architecture

```
Instagram app (user)
  │ shares reel to @shopthereel via DM
  ▼
Meta webhook  ──POST──▶  FastAPI  /webhook            [Meta lane]
                           │ 200 OK immediately
                           ▼ background task
                    media pipeline                      [Meta lane]
                    download video → ffmpeg keyframes
                    → audio → OpenAI transcription
                           │  MediaBundle
                           ▼
                    agent brain                          [Reap lane]
                    OpenAI vision (structured output)
                    → query cascade → Reap product search
                           │  RecognitionResult
                           ▼
                    DM renderer                          [Meta lane]
                    generic template carousel + buttons
                           │  user taps Buy / size / confirm
                           ▼
                    purchase service                     [Reap lane]
                    details → variant → quote → budget guard
                    → checkout → approval URL → poll → order ID
                           │
                           ▼
                    DM renderer: approval button, confirmation
```

Reap handles: card storage, catalog search, product details, live merchant pricing, hosted card-entry page, hosted approval page, merchant checkout.
We build: reel understanding, agent decisions, budget/permission layer, the whole DM experience.

---

## 3. Repo layout

```
shopthereel/
├── PLAN.md                     ← this file
├── AGENTS.md                   ← copy of section 13 (Codex reads this)
├── CLAUDE.md                   ← copy of section 13 (Claude Code reads this)
├── .env.example
├── .gitignore                  ← must include .env, cache/, *.mp4, *.wav
├── requirements.txt
├── app/
│   ├── main.py                 ← FastAPI app, routes mounted here
│   ├── config.py               ← loads env vars (pydantic-settings)
│   ├── models.py               ← SHARED contracts (section 4)
│   ├── state.py                ← SHARED per-user state store (SQLite)
│   ├── meta/                   ← [Meta lane]
│   │   ├── webhook.py          ← GET verify, POST receive, signature check
│   │   ├── send.py             ← Send API wrapper: text, carousel, quick replies, url button
│   │   └── parse.py            ← webhook payload → InboundEvent
│   ├── media/                  ← [Meta lane]
│   │   ├── download.py         ← fetch reel video from payload URL, yt-dlp fallback
│   │   ├── frames.py           ← ffmpeg scene-change keyframes, resize, base64
│   │   └── transcribe.py       ← ffmpeg audio extract + OpenAI transcription
│   ├── dm/                     ← [Meta lane]
│   │   ├── router.py           ← InboundEvent → which handler
│   │   └── render.py           ← RecognitionResult / Quote / Order → DM messages
│   ├── agent/                  ← [Reap lane]
│   │   ├── recognize.py        ← OpenAI vision call, structured output
│   │   ├── prompts.py          ← system prompt + JSON schema
│   │   └── search.py           ← query cascade over Reap search, exact vs similar
│   ├── reap/                   ← [Reap lane]
│   │   ├── client.py           ← thin httpx client, headers, idempotency, errors
│   │   └── schemas.py          ← pydantic models for Reap responses we use
│   └── purchase/               ← [Reap lane]
│       ├── service.py          ← enroll, select variant, quote, checkout, poll
│       └── budget.py           ← budget guard
├── scripts/
│   ├── reap_e2e.py             ← [Reap lane] Phase 1 proof
│   ├── recognize_local.py      ← [Reap lane] run brain on a local MediaBundle
│   ├── media_local.py          ← [Meta lane] run pipeline on a local .mp4
│   └── send_test_dm.py         ← [Meta lane] send a text to a tester IGSID
├── demo_reels/                 ← pre-downloaded demo videos (gitignored)
└── cache/                      ← recognition cache by reel id (gitignored)
```

---

## 4. Shared contracts (`app/models.py`)

Commit this at the 4:15 pm sync. **Do not change it without telling the other person.** Both lanes code against these types.

```python
from pydantic import BaseModel
from typing import Literal, Optional

# ---------- Meta lane produces ----------

class MediaBundle(BaseModel):
    reel_id: str                    # ig video id or file hash, used as cache key
    frames_b64: list[str]           # max 8 JPEGs, ~768px wide, base64
    caption: Optional[str] = None   # ig_reel payload "title"
    transcript: Optional[str] = None
    user_hint: Optional[str] = None # text the user sent with/after the reel, e.g. "the jacket"

# ---------- Reap lane produces ----------

class DetectedProduct(BaseModel):
    name: str
    category: str
    brand: Optional[str] = None
    brand_source: Literal["caption", "speech", "visible_logo", "none"]
    attributes: list[str]
    queries: list[str]              # [specific, descriptive, broad]
    best_frame: int
    confidence: float

class ProductCandidate(BaseModel):
    product_id: str
    name: str
    merchant: str
    image_url: Optional[str] = None
    price_min: float
    price_max: float
    currency: str
    default_variant_id: Optional[str] = None

class RecognitionResult(BaseModel):
    detected: DetectedProduct
    match_type: Literal["exact", "similar", "none"]
    query_used: Optional[str] = None
    candidates: list[ProductCandidate]   # top 3

class VariantOption(BaseModel):
    group: str                      # "Size", "Color"
    label: str
    option_id: str
    available: bool

class QuoteSummary(BaseModel):
    quote_id: str
    items_subtotal: float
    shipping: float
    tax: float
    final_amount: float
    currency: str
    expires_at: str
    within_budget: bool
    budget_message: Optional[str] = None

class OrderResult(BaseModel):
    checkout_id: str
    status: str                     # REQUIRES_ACTION, COMPLETED, FAILED...
    approval_url: Optional[str] = None
    order_id: Optional[str] = None
    final_amount: Optional[float] = None
    currency: Optional[str] = None
```

### Function interfaces each lane exposes

**Reap lane exposes** (Meta lane calls these from DM handlers):

```python
# app/agent/search.py
async def recognize_and_search(bundle: MediaBundle) -> RecognitionResult: ...

# app/purchase/service.py
async def ensure_enrollment(user_id: str) -> str | None:
    """Returns hosted card-entry URL if user not enrolled, else None."""
async def get_options(product_id: str) -> list[VariantOption]: ...
async def resolve_variant(product_id: str, option_ids: list[str]) -> str: ...  # variant_id
async def create_quote(user_id: str, variant_id: str) -> QuoteSummary: ...
async def start_checkout(user_id: str, quote_id: str) -> OrderResult: ...
async def poll_checkout(checkout_id: str) -> OrderResult: ...

# app/purchase/budget.py
def set_budget(user_id: str, per_order: float, currency: str) -> None: ...
def get_budget(user_id: str) -> tuple[float, str] | None: ...
```

**Meta lane exposes** (Reap lane rarely needs these, but the purchase poller uses them):

```python
# app/meta/send.py
async def send_text(igsid: str, text: str) -> None: ...
async def send_carousel(igsid: str, result: RecognitionResult) -> None: ...
async def send_quick_replies(igsid: str, text: str, options: list[tuple[str, str]]) -> None: ...  # (title, payload)
async def send_url_button(igsid: str, text: str, title: str, url: str) -> None: ...
```

### Postback payload format (both lanes must agree)

Plain strings, colon separated, max ~1000 chars:

| Payload | Meaning |
|---|---|
| `BUY:<product_id>` | User tapped Buy on a carousel card |
| `OPT:<product_id>:<option_id>` | User picked a size/color option |
| `CONFIRM:<quote_id>` | User accepts the quote, start checkout |
| `CANCEL` | User cancels current flow |
| `MORE:<reel_id>` | Show next 3 candidates (stretch) |

### Per-user state (`app/state.py`)

SQLite table `users`, keyed by Instagram-scoped ID (IGSID):

```
igsid TEXT PRIMARY KEY
enrollment_id TEXT
budget_per_order REAL
budget_currency TEXT
shipping_json TEXT            -- demo default address
pending_product_id TEXT
pending_option_ids TEXT        -- JSON list
pending_quote_id TEXT
pending_checkout_id TEXT
updated_at TEXT
```

Table `recognitions`: `reel_id TEXT PRIMARY KEY, result_json TEXT` (cache).
Table `orders`: `checkout_id, igsid, order_id, final_amount, currency, created_at`.

---

## 5. Environment variables (`.env.example`)

```
# Reap (Reap lane)
REAP_API_KEY=
REAP_BASE_URL=https://sandbox.api.reap.global
REAP_VERSION=                 # value from Reap docs / kickoff
REAP_DEFAULT_COUNTRY=SG       # confirm which country/currency the sandbox catalog supports
REAP_DEFAULT_CURRENCY=SGD
REAP_SIMULATE_CHECKOUT=true   # adds X-Simulate-Checkout: COMPLETED
REAP_RETURN_URL=https://<ngrok>/done
DEMO_EMAIL=
DEMO_SHIPPING_JSON={"firstName":"Demo","lastName":"User","phone":"+6500000000","addressLine1":"65 Mohamed Sultan Rd","city":"Singapore","postalCode":"239002","country":"SG"}

# OpenAI (Reap lane uses vision, Meta lane uses transcription)
OPENAI_API_KEY=
OPENAI_VISION_MODEL=          # strongest vision model on the credited account
OPENAI_TRANSCRIBE_MODEL=      # transcription model on the credited account

# Meta (Meta lane)
IG_ACCESS_TOKEN=
IG_BUSINESS_ACCOUNT_ID=
META_APP_SECRET=              # for X-Hub-Signature-256 verification
META_VERIFY_TOKEN=            # any random string, also entered in Meta dashboard
GRAPH_API_VERSION=            # latest version shown in the Meta dashboard

# App
PUBLIC_BASE_URL=https://<ngrok-subdomain>.ngrok-free.app
DB_PATH=./shopthereel.db
```

**Never commit `.env`. Never print these values in logs.**

---

## 6. Phase plan

Times are targets. If a phase overruns by more than 20 minutes, drop to the fallback listed in that phase.

### Phase 0 | Setup and blockers (3:45-4:30 pm)

**Both (first 10 min)**
- [ ] Create GitHub repo, push this file as `PLAN.md`, copy section 13 into `AGENTS.md` and `CLAUDE.md`
- [ ] Prakhar registers the team on the Reap Buildathon Teams page with both Luma emails (**before 4:30 pm**)
- [ ] Both claim OpenAI credits; note which vision and transcription models are available
- [ ] Python 3.11+ venv, `pip install fastapi uvicorn httpx pydantic pydantic-settings openai python-dotenv yt-dlp`; install `ffmpeg`

**Prakhar | Reap lane**
- [ ] Read Reap Agentic docs: Setup, One-Time Purchases, Lifecycle (15 min max)
- [ ] When key arrives: put it in `.env`, call `GET` on a cheap endpoint to confirm auth works
- [ ] Open the merchant sheet; shortlist 3 product types for demo reels (e.g. headphones, sneakers, a coffee item)
- [ ] Raw `POST /agentic/products/search` for each, confirm results come back for the chosen country/currency
- [ ] Find 3 demo reels on Instagram featuring those product types; save their links in `demo_reels/README.md`

**Pratham | Meta lane**
- [ ] Create a new Instagram account `@shopthereel` (or similar), switch to Professional (Creator or Business)
- [ ] In that account's settings, allow connected tools to access messages
- [ ] developers.facebook.com → create app → add Instagram product → "Instagram API with Instagram Login"
- [ ] Connect `@shopthereel`, generate access token with `instagram_business_basic` and `instagram_business_manage_messages`
- [ ] App roles → add Prakhar's and Pratham's personal Instagram accounts as Instagram testers; both accept invites (in Instagram app settings / website)
- [ ] Start `ngrok http 8000`, note the HTTPS URL

**Done when:**
- Reap key works and searches return products for all 3 demo product types
- Meta app exists, token generated, testers invited

**Fallback:** if Meta tester invites are stuck past 5:30 pm, Meta lane switches the front door to a Telegram bot (same `MediaBundle` interface, same renderer concepts) and keeps trying Meta in the background.

---

### Phase 1 | Foundations (4:30-5:30 pm)

**Prakhar | Reap lane: prove one purchase end to end**

- [ ] `app/reap/client.py`
  - `httpx.AsyncClient(base_url=REAP_BASE_URL, timeout=30)`
  - Default headers: `Authorization: Bearer <key>`, `Reap-Version: <version>`, `Content-Type: application/json`
  - Every POST that creates something gets `Idempotency-Key: <uuid4>`
  - Checkout POST adds `X-Simulate-Checkout: COMPLETED` when `REAP_SIMULATE_CHECKOUT=true`
  - Raise a typed `ReapError(code, message, status)` from error responses; never log request bodies containing addresses or emails in full
- [ ] Enrollment: `POST /agentic/enrollments` (type `EXTERNAL`), open the returned hosted URL in a browser, enter the sandbox card + OTP, then `GET /agentic/enrollments/:id` until `ACTIVE`. Save the ID.
- [ ] `scripts/reap_e2e.py`, hardcoded query, in order:
  1. `POST /agentic/products/search` `{query, context:{country,currency}, filters:{availability:"AVAILABLE_ONLY"}, pagination:{limit:5}}`
  2. `POST /agentic/products/details` `{productIds:[id]}`
  3. If options exist: `POST /agentic/products/variant` `{productId, optionIds}`; else use `defaultVariant.id`
  4. `POST /agentic/quotes` `{items:[{variantId, quantity:1}], email, shippingAddress}` (include address when `requiresShipping`)
  5. Optional: `POST /agentic/quotes/:id/shipping-option` to pick the cheapest option
  6. `POST /agentic/checkouts` `{quoteId, enrollmentId, presentation:{type:"REDIRECT", returnUrl}}`
  7. If `nextAction.url`: print it, open it, approve
  8. Poll `GET /agentic/checkouts/:id` every 2 s, max 60 s, until terminal status
  9. Print `orderId` and `finalAmount`

**Pratham | Meta lane: webhook live**

- [ ] `app/main.py` with FastAPI, mount `meta/webhook.py`
- [ ] `GET /webhook`: if `hub.mode == "subscribe"` and `hub.verify_token == META_VERIFY_TOKEN`, return `hub.challenge` as plain text, else 403
- [ ] `POST /webhook`: verify `X-Hub-Signature-256` (HMAC SHA256 of raw body with `META_APP_SECRET`), log the full JSON body to console for now, return 200 within 1 s
- [ ] In Meta dashboard: set callback URL `https://<ngrok>/webhook`, verify token, subscribe to `messages` (and `messaging_postbacks` if listed separately)
- [ ] `app/meta/send.py: send_text()` → `POST https://graph.instagram.com/<GRAPH_API_VERSION>/me/messages` with `Authorization: Bearer <IG_ACCESS_TOKEN>`, body `{"recipient":{"id":igsid},"message":{"text":...}}` (confirm exact path and version in the Meta docs for Instagram API with Instagram Login)
- [ ] From a tester account, DM `@shopthereel` "hi", see the webhook log, reply "hello" via `send_text`
- [ ] Share a reel to `@shopthereel`, **save the raw webhook JSON** to `docs/sample_ig_reel_webhook.json`. Check: is `payload.url` a direct video file? Note the result in this file under section 10.

**Done when (5:30 pm sync):**
- `python scripts/reap_e2e.py` prints a merchant order ID
- A DM to the bot is received and answered; a real `ig_reel` payload is saved

---

### Phase 2 | Core pipelines (5:30-6:45 pm)

**Prakhar | Reap lane: the agent brain**

- [ ] `app/agent/prompts.py`: system prompt (section 8) + JSON schema for `DetectedProduct`
- [ ] `app/agent/recognize.py`
  - One OpenAI chat/responses call with: system prompt, then user content = caption, transcript, user_hint as text + each frame as an image input (`data:image/jpeg;base64,...`, detail low or auto)
  - Use structured outputs (JSON schema, strict) so the response always parses into `DetectedProduct`
  - Timeout 45 s, one retry on timeout
- [ ] `app/agent/search.py: recognize_and_search(bundle)`
  - Check `recognitions` cache by `reel_id` first
  - Call `recognize()`
  - Query cascade: for `i, q in enumerate(detected.queries)`: search Reap with `limit 5`; stop at the first non-empty result. `match_type = "exact"` if `i == 0` and brand present, `"similar"` otherwise, `"none"` if all empty
  - If user has a budget, pass `filters.price.max`
  - Map to top 3 `ProductCandidate`, cache, return
- [ ] `scripts/recognize_local.py`: build a `MediaBundle` from a folder of JPEGs + caption text and print the `RecognitionResult`
- [ ] Tune prompt on the 3 demo reels (use frames the Meta lane gives you, or screenshots)

**Pratham | Meta lane: media pipeline**

- [ ] `app/media/download.py`: given the `ig_reel` payload, `httpx` GET the `url`; if content-type is not video, fall back to `yt-dlp` on the share URL; save to `/tmp/<reel_id>.mp4`; size cap 50 MB
- [ ] `app/media/frames.py`
  - `ffmpeg -i in.mp4 -vf "select='gt(scene,0.3)',scale=768:-2" -vsync vfr -frames:v 8 out_%02d.jpg`
  - If fewer than 4 frames, fall back to `-vf "fps=1,scale=768:-2"` and take up to 8 evenly spaced
  - Return base64 list
- [ ] `app/media/transcribe.py`: `ffmpeg -i in.mp4 -vn -ac 1 -ar 16000 out.wav`, send to OpenAI transcription; return text or `None` on failure (never block the pipeline on transcription)
- [ ] `scripts/media_local.py`: `.mp4` in → `MediaBundle` JSON out (save to `demo_reels/<name>.bundle.json` so Prakhar can test with it)
- [ ] `app/meta/parse.py`: webhook JSON → `InboundEvent{igsid, kind: "reel"|"text"|"postback"|"quick_reply", reel_url, reel_title, reel_id, text, payload}`
- [ ] `app/meta/send.py`: add `send_carousel`, `send_quick_replies`, `send_url_button` (formats in section 9)

**Done when (6:45 pm sync):**
- A `.mp4` goes through Meta lane's pipeline → `MediaBundle` → Reap lane's brain → `RecognitionResult` with sensible candidates for all 3 demo reels

**Fallback:** if transcription is flaky, skip it (`transcript=None`). If scene detection is flaky, use fixed 1 fps.

---

### Phase 3 | Integration: reel in DM → product cards (6:45-7:30 pm)

**Pratham | Meta lane (leads this phase)**
- [ ] `app/dm/router.py`
  - `kind == "reel"` → `send_text("Looking at this reel 👀")` → background task: download → bundle → `recognize_and_search` → `render.results()`
  - `kind == "text"`: handle commands (section 7), else treat as `user_hint` for the most recent reel
  - `kind in ("postback","quick_reply")` → dispatch by payload prefix (section 4)
- [ ] `app/dm/render.py: results(igsid, result)`
  - `match_type == "exact"`: "Found it! Here's where you can get it:"
  - `"similar"`: "Couldn't find that exact one, here are close matches:"
  - `"none"`: "I couldn't find this in our stores. Try sending a clearer reel or tell me what you're after."
  - Then carousel: title = product name (truncate 80), subtitle = `"{merchant} | {currency} {price}"`, image = `image_url`, button postback `BUY:<product_id>`

**Prakhar | Reap lane**
- [ ] Add `ensure_enrollment`, `get_options`, `resolve_variant` in `purchase/service.py`
- [ ] Add `budget.py` (section 7)
- [ ] Pair with Pratham on the first live integration run; fix contract mismatches immediately

**Done when:** sharing a demo reel from a tester phone shows a "looking" message, then a product carousel in under ~30 s.

---

### Phase 4 | Buying in the DM (7:30-8:00 pm)

**Prakhar | Reap lane**
- [ ] `create_quote(user_id, variant_id)`: quote with demo email + `DEMO_SHIPPING_JSON`, pick cheapest shipping option, compute `within_budget` from `final_amount` vs user budget, build `budget_message`
- [ ] `start_checkout(user_id, quote_id)`: create checkout, return `OrderResult` with `approval_url`
- [ ] `poll_checkout`: background poll every 2 s up to 120 s; on `COMPLETED` call `send_text` with confirmation and insert into `orders`; on failure send a clear error
- [ ] Handle errors by code: `QUOTE_UNFULFILLABLE` / expired quote → re-quote once; `CARD_PAYMENT_UNAVAILABLE` → tell user to pick another product

**Pratham | Meta lane**
- [ ] `BUY:<product_id>`
  1. If not enrolled: `send_url_button("First, add a card securely with Reap. I never see your card details.", "Add card", url)` and stop
  2. Get options; if any group has more than one available value, send quick replies `OPT:<product_id>:<option_id>` (one group at a time); else go straight to quote
- [ ] `OPT:...`: store option, ask next group or resolve variant → quote
- [ ] Render quote: "Subtotal X, shipping Y, tax Z, **total T**". If `within_budget`: quick replies `Confirm` (`CONFIRM:<quote_id>`) / `Cancel`. Else: send `budget_message` and stop
- [ ] `CONFIRM:<quote_id>`: `start_checkout` → `send_url_button("Approve the payment on Reap's secure page:", "Approve payment", approval_url)` → start poller
- [ ] Final message: "✅ Ordered! Order #<orderId>, <currency> <amount> charged."

**Done when:** from a phone: share reel → tap Buy → pick size → see total → Confirm → approve on Reap page → order confirmation in DM.

---

### Phase 5 | Freeze, polish, submit (8:00-9:00 pm)

**8:00 pm: feature freeze.**

**Prakhar**
- [ ] Error handling pass on Reap + OpenAI paths; every failure produces a friendly DM, never silence
- [ ] Warm the cache: run all 3 demo reels once
- [ ] README: problem, demo GIF/video link, architecture diagram (section 2), how Reap is used (list of endpoints), how permission and budget work, setup steps, future work

**Pratham**
- [ ] Record the backup demo video (screen-record phone + laptop), 90-120 s, following the demo script (section 11)
- [ ] Make sure the webhook handler never crashes on unknown event types (stickers, reactions, read receipts): log and ignore

**Both**
- [ ] 8:30 pm: rehearse the pitch twice
- [ ] 8:45 pm: last push, tag `v1-submission`
- [ ] Submit via the portal before 9:00 pm with repo link + video

---

### Stretch (only if a phase finished early; never after 7:45 pm)

| Stretch | Owner | Effort |
|---|---|---|
| Visual re-ranking: second OpenAI vision call comparing `best_frame` with each candidate `image_url`, reorder by score | Prakhar | 30 min |
| `MORE:<reel_id>` "show more options" button | Pratham | 15 min |
| Multi-product reels: return list of `DetectedProduct`, ask "which one?" via quick replies | Both | 45 min |
| Kwal wallet payment as second pay option (targets "Best Bridge Between Onchain and Real World" track): check first whether the Kwal skill exposes a CLI/API our backend can call | Whoever is free | 60+ min, high risk |
| Typing indicator / "seen" sender actions while processing | Pratham | 10 min |

---

## 7. Budget and permission layer (`app/purchase/budget.py`)

This is a judging point: "agent can buy with a person's permission and spending limits". Reap mandates are not live in sandbox yet, so we enforce limits ourselves, on top of Reap's hosted per-charge approval.

**Commands (text DMs):**

| Command | Effect |
|---|---|
| `budget 150` | Per-order limit = 150 in default currency |
| `budget` | Show current limit |
| `budget off` | Remove limit (ask to confirm) |
| `help` | How to use the bot |

**Rules:**
1. Search uses `filters.price.max = budget` when a budget exists.
2. After quoting, compare `final_amount` (includes shipping + tax) with budget. Over budget → refuse with: "That comes to T with shipping and tax, which is over your limit of B. Want to raise your budget or pick something cheaper?"
3. Agent never creates a checkout without an explicit `CONFIRM:<quote_id>` tap from the same IGSID.
4. Every charge still needs approval on Reap's hosted page.
5. Card details never pass through our server or the model.

Pitch line: **three layers of control: your budget, your tap to confirm, and Reap's approval page. The AI physically cannot spend on its own.**

---

## 8. OpenAI recognition prompt (`app/agent/prompts.py`)

**System prompt:**

```
You identify purchasable products shown in short social media videos (Instagram reels).

You receive: up to 8 frames from the video, the creator's caption, a speech transcript,
and optionally a hint from the user about which item they want.

Task: identify the ONE product the user most likely wants to buy.
- If the user hint names an item ("the jacket"), pick that item.
- Otherwise pick the most prominent featured product (close-ups, the item being talked about or tagged).

Evidence priority for brand and model:
1. Brand or product named in the caption (including @tags and #tags)
2. Brand or product named in the speech transcript
3. Logos or text clearly visible in the frames
If none of these, set brand to null and brand_source to "none". Never guess a brand.

Write exactly 3 search queries for an e-commerce catalog, from most to least specific:
1. specific: brand + model/product name + key attribute (if brand unknown, the most precise description possible)
2. descriptive: no brand, 3-5 key visual attributes + product type
3. broad: product type only, 1-3 words

Queries must be short, plain words a shop search box understands. No hashtags, no emojis.
Set best_frame to the 0-based index of the frame that shows the product most clearly.
Set confidence between 0 and 1 for how sure you are of the identification.
```

**JSON schema:** mirror `DetectedProduct` from section 4, all fields required, `brand` nullable, `brand_source` enum, `queries` array of exactly 3 strings, `additionalProperties: false`.

**Cost/latency rules:**
- Max 8 frames, ~768px wide
- Cache by `reel_id`
- If caption already names a brand clearly, transcription may be skipped for speed

---

## 9. Instagram message formats (`app/meta/send.py`)

All via `POST https://graph.instagram.com/<GRAPH_API_VERSION>/me/messages`, header `Authorization: Bearer <IG_ACCESS_TOKEN>`. Verify exact field names against current Meta docs during Phase 1; adjust here if they differ.

**Text**
```json
{"recipient":{"id":"<IGSID>"},"message":{"text":"Looking at this reel 👀"}}
```

**Carousel (generic template), up to 10 elements, we use 3**
```json
{
  "recipient": {"id": "<IGSID>"},
  "message": {
    "attachment": {
      "type": "template",
      "payload": {
        "template_type": "generic",
        "elements": [
          {
            "title": "Sony WH-1000XM5 Headphones",
            "image_url": "https://...",
            "subtitle": "AudioHub | SGD 429",
            "buttons": [
              {"type": "postback", "title": "Buy", "payload": "BUY:<product_id>"}
            ]
          }
        ]
      }
    }
  }
}
```

**Quick replies (max 13, titles ~20 chars)**
```json
{
  "recipient": {"id": "<IGSID>"},
  "message": {
    "text": "Which size?",
    "quick_replies": [
      {"content_type": "text", "title": "M", "payload": "OPT:<product_id>:<option_id>"}
    ]
  }
}
```

**URL button (approval / enrollment link)**: generic template with one element and a `web_url` button, or a button template if supported:
```json
{"type": "web_url", "url": "<approval_url>", "title": "Approve payment"}
```

**Inbound shapes to parse** (`app/meta/parse.py`):
- Reel: `entry[].messaging[].message.attachments[]` with `type` in `ig_reel`, `reel`, `video`; `payload.url`, `payload.title`, `payload.reel_video_id` (confirm key name from the saved sample)
- Text: `message.text`
- Quick reply tap: `message.quick_reply.payload`
- Button tap: `messaging[].postback.payload`
- Ignore: `message.is_echo == true` (our own messages), reads, reactions

Constraints: replies only within 24 h of the user's last message; only tester accounts work in dev mode.

---

## 10. Findings log (fill in during the build)

| Question | Answer |
|---|---|
| Reap-Version header value | |
| Sandbox country/currency that returns products | |
| Demo product types that fully quote + checkout | |
| `ig_reel` `payload.url` is a direct video file? | |
| `ig_reel` video id key name | |
| Graph API version + messages endpoint confirmed | |
| Vision model used | |
| Transcription model used | |
| Average end-to-end time reel → carousel | |

---

## 11. Demo script (90-120 seconds)

1. **Problem (15 s):** "You see something you love in a reel. Then you screenshot it, Google it, give up. Shopping from reels is broken."
2. **Share (15 s):** On phone, open a demo reel → Share → send to `@shopthereel`. Bot: "Looking at this reel 👀"
3. **Recognise (15 s):** Carousel appears. Point out "Found it" vs "close matches" honesty.
4. **Budget (15 s):** Show `budget 150` was set earlier; optionally tap a too-expensive item to show the refusal.
5. **Buy (20 s):** Tap Buy → size → total with shipping and tax → Confirm.
6. **Approve (15 s):** Reap-hosted page opens, approve. Back in DM: "✅ Ordered! Order #..."
7. **Trust (10 s):** "The AI never saw the card. Three layers: your budget, your confirm, Reap's approval."
8. **Close (5 s):** "Every reel becomes a storefront, and the buyer stays in control."

Prize fit: **Most Worthwhile Problem** (primary). If Kwal stretch works, also **Best Bridge Between Onchain and Real World**.

---

## 12. Risks and fallbacks

| Risk | Likelihood | Fallback |
|---|---|---|
| Meta tester invites / token issues | High | Telegram bot front door by 5:30 pm, same pipeline |
| `ig_reel` URL not downloadable | Medium | `yt-dlp` on share URL; else use pre-downloaded `demo_reels/` mapped by reel id |
| Demo product not in Reap catalog | Medium | Choose demo reels only from verified product types (Phase 0) |
| Quote expires before confirm | Medium | Re-quote automatically once on confirm |
| OpenAI slow on stage | Medium | Warm cache for demo reels |
| ngrok URL changes on restart | Medium | Don't restart ngrok after 7 pm; if forced, update Meta callback URL immediately |
| Webhook retries cause duplicate processing | Medium | Dedupe on `message.mid` in a set/table |
| Live demo fails | Any | Backup video recorded by 8:40 pm |

---

## 13. Rules for coding agents (copy into AGENTS.md and CLAUDE.md)

```
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
```

### Starter prompts

**Prakhar (Codex/Claude), Phase 1:**
> Read PLAN.md sections 4, 5 and 6 (Phase 1, Reap lane). Implement `app/config.py`, `app/reap/client.py` and `scripts/reap_e2e.py` exactly as described. Async httpx, typed `ReapError`, idempotency keys, simulate header from env. The script takes `--query` and `--enrollment-id` args and prints each step's key fields and the final order ID.

**Prakhar, Phase 2:**
> Read PLAN.md sections 4 and 8. Implement `app/agent/prompts.py`, `app/agent/recognize.py` (OpenAI vision with strict JSON schema structured output for `DetectedProduct`) and `app/agent/search.py` (`recognize_and_search` with cache and 3-query cascade over the Reap client). Add `scripts/recognize_local.py` that loads a `MediaBundle` JSON file and prints the `RecognitionResult`.

**Prakhar, Phase 3-4:**
> Read PLAN.md sections 4, 6 (Phase 3-4, Reap lane) and 7. Implement `app/purchase/service.py` and `app/purchase/budget.py` with the exact function signatures in section 4. Use `app/state.py` for persistence. Include the checkout poller that calls `app.meta.send.send_text` on completion.

**Pratham (Codex/Claude), Phase 1:**
> Read PLAN.md sections 4, 5, 6 (Phase 1, Meta lane) and 9. Implement `app/main.py` and `app/meta/webhook.py`: GET verification, POST with X-Hub-Signature-256 verification, log body, return 200 fast. Implement `send_text` in `app/meta/send.py`. Add `scripts/send_test_dm.py`.

**Pratham, Phase 2:**
> Read PLAN.md sections 4 and 6 (Phase 2, Meta lane). Implement `app/media/download.py`, `frames.py`, `transcribe.py` and `scripts/media_local.py` producing a `MediaBundle` JSON. Implement `app/meta/parse.py` and the remaining senders in `app/meta/send.py` using formats in section 9.

**Pratham, Phase 3-4:**
> Read PLAN.md sections 4, 6 (Phase 3-4, Meta lane), 7 and 9. Implement `app/dm/router.py` and `app/dm/render.py`: reel handling in a background task, commands, postback/quick-reply dispatch by payload prefix, and all DM messages described. Call the Reap lane functions from section 4; do not reimplement them.

---

## 14. Submission checklist

- [ ] Repo public (or shared), `.env` not committed, no keys in history
- [ ] README: problem, demo video, architecture, Reap endpoints used, permission/budget design, setup, future work (Reap mandates, Kwal wallet, Lens-style visual search, multi-item reels, public app review)
- [ ] Demo video 90-120 s
- [ ] Both team members listed
- [ ] Submitted before **9:00 pm sharp**
