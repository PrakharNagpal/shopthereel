# ShopTheReel

**Every reel becomes a storefront, and the buyer stays in control.**

Built for the Reap x 65labs Agentic Buildathon (Singapore, 9 October 2026) by Prakhar Nagpal and Pratham Ranjan.

Send a bot an Instagram reel. An AI agent works out which product is in it, finds it (or the closest look-alikes) in Reap's merchant catalog, quotes the real price with shipping and tax, checks the order against the buyer's own spending rules, and completes the purchase only after the buyer approves the charge on a Reap-hosted page. The AI never sees the card.

## The problem

You see something you love in a reel. Then you screenshot it, search for it, and give up. Reels almost never show a brand name or a product link, so the "last mile" from inspiration to purchase is broken. Letting an AI agent close that gap raises a second problem: nobody wants an agent that can spend their money on its own.

## What it does

1. **Share a reel.** The user sends a reel link (Telegram) or shares the reel in a DM (Instagram implementation).
2. **Understand it.** The bot downloads the reel, pulls keyframes and the audio transcript, and asks a vision model to identify the featured product. Most reels show no readable brand, so the agent describes the product visually and builds three search queries, from specific to broad.
3. **Find it.** All three queries run against Reap's catalog. The vision model then compares the reel frame with each candidate's photo and ranks them by how they look. Cards are labelled **Best match**, **Best value** or **Cheapest close match**. A result is called "exact" only if a candidate really carries the detected brand or model number, so the bot never claims "found it" when it only found something similar.
4. **Buy in the chat.** Tap Buy, pick a size or colour, see subtotal, shipping, tax and total, and tap Confirm.
5. **Approve on Reap.** The bot sends Reap's hosted approval link. After the user approves, the bot reports the order number and amount.
6. **Follow-up.** After an order completes, the bot suggests real add-ons (for headphones: a stand or a case, not more headphones).

## Trust: four layers of control

The AI physically cannot spend on its own.

| Layer | What it does |
|---|---|
| **Spending rules** (ours) | Interactive `settings` menu: per-order limit, monthly limit, orders per day, a pause switch, and an extra "are you sure?" tap above an amount the user chooses. Checked against every quote, including shipping and tax, before a Confirm button is shown. |
| **Explicit tap** (ours) | A checkout is created only from a Confirm tap by the same user, on the quote that user last saw. Tapped buttons are removed so a double tap cannot confirm twice. |
| **Reap's approval page** | Every charge needs the user to approve it on Reap's hosted page. |
| **No card data** | Card entry happens only on Reap's hosted page. We store an enrollment ID, never card details. Card numbers typed into the chat are refused, and no card data goes to any model or log. |

Reap's own mandates (pre-approved spending terms) are not available in the sandbox yet. Our rules are built to run alongside them when they ship.

## How Reap Agentic is used

All product data and purchases go through the Agentic module. Nothing is scraped from merchant sites.

| Step | Endpoint |
|---|---|
| Store a card | `POST /agentic/enrollments` (source `EXTERNAL`, hosted card entry), `GET /agentic/enrollments/:id` |
| Find products | `POST /agentic/products/search` |
| Product details and options | `POST /agentic/products/details` |
| Pick a size or colour | `POST /agentic/products/variant` |
| Price the order | `POST /agentic/quotes`, `POST /agentic/quotes/:id/shipping-option` |
| Pay | `POST /agentic/checkouts` (REDIRECT presentation), `GET /agentic/checkouts/:id` |

Every call sends `Authorization`, `Reap-Version: 2025-02-14` and, on creating requests, an `Idempotency-Key`. The client retries Reap's transient 502 and 503 responses with the same idempotency key, so a retry cannot create a duplicate. Checkout runs with `X-Simulate-Checkout: COMPLETED`, so nothing ships.

## Architecture

```
Instagram reel link / DM share
        |
   Telegram bot  (root)      or      Instagram webhook  (instagram/)
        |
        v
  media pipeline   yt-dlp download -> ffmpeg keyframes -> audio transcript
        |
        v
  agent            vision model -> 3 queries -> Reap search -> visual rerank -> badges
        |
        v
  chat router      cards, options, quote, spending rules, extra confirm
        |
        v
  purchase         enrollment -> variant -> quote -> checkout -> Reap approval -> order
        |
        v
  order message + add-on suggestions
```

Both front doors follow this design. The Telegram implementation lives at the repository root. The Instagram implementation is an independent copy in [instagram/](instagram/), with its own Meta webhook, validated download of media shared in DMs (videos and images from Meta's CDN only), a web-checkout API, and a bridge to the existing Reel Brain app. See [instagram/README.md](instagram/README.md).

## Chat about the reel, and personal context

After the product cards, the bot offers **Chat more**. In that mode the shopper can ask for a cheaper alternative, compare two products, or ask what a recipe needs. The chat is a tool-using agent that can only read: it can search the catalog, open product details, read the shopper's saved preferences and present products. Cart, order and payment tools are switched off, product cards always come from catalog data, never from model text, prices never appear in generated prose, and the shopper's budget is applied to every search. Buying still goes through the Buy buttons, the spending rules and Reap's approval.

The agent also uses what a shopper tells it. It remembers what they own (for example an oven but no air fryer) and what is in their pantry, always after an explicit "Remember that you have X?" confirmation. Shown a recipe reel, it can offer both options: buy the appliance, or cook with what they already have. It never invents recipe steps or conversions, labels sample data as assumptions, and add-on suggestions after an order skip equipment the shopper already owns.

## Open source used

The chat agent runs on the shopping core from Anthropic's open-source [commerce-agents](https://github.com/anthropics/commerce-agents) blueprint (Apache-2.0, pinned revision, license and notices kept), vendored unchanged in [third_party/commerce-agents](third_party/commerce-agents). We wrote the storefront adapter that connects it to Reap's catalog ([app/agent/commerce.py](app/agent/commerce.py)) and drive it with an OpenAI model. No Claude API calls are made.

## Showcase website

[frontend/reel-commerce](frontend/reel-commerce) is a Next.js website that tells the story visually: a phone in the centre with Instagram, Telegram and TikTok scenes scrolling past, and an illustrative simulated checkout. It has a separate local account area (salted scrypt password hashes, HttpOnly session cookies, rate limiting). It is not connected to the bot or to any payment API.

## What is real and what is simulated

- **Real:** Reap sandbox search, quotes, enrollment and checkouts. Orders completed end to end in testing (for example SGD 44.90 and SGD 259.90). Real OpenAI vision, speech and ranking calls. Real downloads of Instagram reel links.
- **Simulated:** checkout is simulated by Reap's sandbox, so no real purchase or shipment happens. Money is sandbox only.
- **Honest limits:** the vision model sometimes cannot read a logo and may misspell a brand, which is why "exact" has to be earned by a catalog match. Reap's sandbox returns intermittent 503 errors and can take about a minute to process a payment after approval. On Telegram, links to photo posts and carousels cannot be downloaded, only videos and reels. The Instagram front door is covered by mocked tests, and live delivery depends on Meta's tester and permission setup. The `instagram/` copy does not yet include the Chat more agent, which lives in the Telegram implementation.

## Run it

Requires Python 3.11 and ffmpeg. Installing the requirements also installs the vendored commerce core from `third_party/`.

```sh
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env     # fill in the Reap and OpenAI keys, model names and Telegram bot token
.venv/bin/uvicorn app.main:app --port 8000
```

Set `TELEGRAM_BOT_TOKEN` from @BotFather and `TELEGRAM_ALLOWED_CHAT_IDS` to the chat IDs allowed to spend. Set `DEMO_ENROLLMENT_ID` to a sandbox enrollment that is already `ACTIVE` to skip card entry in demos. Keys live only in `.env`, which is never committed.

Tests (all use mocked external services except where noted):

```sh
.venv/bin/python -m unittest discover -s app/agent -p 'test_*.py'      # 17 tests
cd instagram && ../.venv/bin/python -m unittest discover -s tests -p 'test_*.py'   # 40 tests
cd frontend/reel-commerce && node auth/test.mjs                          # 9 account checks
```

The purchase flow itself was verified against the live Reap sandbox, with completed orders.

## Future work

- Reap mandates and Spend Policies, so limits are also enforced on Reap's side.
- Photo posts and carousels from links, and reels with several products ("which one?").
- A second visual search pass on the live catalog, in the style of a visual search lens.
- Public Meta app review so any Instagram user can use the bot, beyond testers.
- A wallet-based second payment option.
