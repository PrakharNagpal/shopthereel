# Instagram commerce

Independent Instagram implementation of ShopTheReel. The repository root retains the Telegram implementation. Run this service from this folder with its own environment and database.

Share a Reel in Instagram DMs, receive identified products from Reap merchants, choose a variant, review shipping/tax/total, and confirm. Card enrollment and payment approval use Reap-hosted pages. Payment status and order confirmation return to the same DM. Sandbox checkout is simulated and does not ship goods.

Includes personal inventory and pantry memory, preferences, Reel follow-up questions, recipe alternatives using owned appliances, optional complementary products, spending limits, pause/resume, and extra purchase confirmation. Each Instagram user starts with an empty, separate profile. Recommendations do not automatically buy products.

## Setup

Requires Python 3.11 and ffmpeg on PATH.

```sh
cd instagram
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Fill the private `.env` with your Reap and OpenAI credentials/model names, Instagram business account token/ID, Graph API version, Meta app secret and verification token. Set `DEMO_EMAIL` and `DEMO_SHIPPING_JSON` to valid sandbox buyer/shipping details for quoting. Set `REAP_RETURN_URL` to the desired return link, such as your Instagram bot's `https://ig.me/m/<username>`. Leave `DEMO_ENROLLMENT_ID` blank for individual enrollment; a sandbox-only ACTIVE enrollment can be supplied for a shared demo. Never commit `.env` or the database.

```sh
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8101
```

For direct Meta delivery, expose the backend through HTTPS and configure `/webhook` as the Meta callback, using your verification token and the messages/messaging_postbacks subscriptions. Incoming requests require the Meta signature. The account and app must have the appropriate messaging permissions/tester setup.

## Existing Reel Brain webhook

`integrations/reel-brain/` contains the Next.js route and supporting libraries used by the existing Reel Brain front door. Copy those files into that Next.js app, preserving their paths, and configure the example variables in its `.env.local`. `COMMERCE_API_TOKEN` must equal this backend's `WEB_API_TOKEN`. Use a private backend URL accessible to the Next.js process. With `INSTAGRAM_COMMERCE_ENABLED=true`, its signed `/api/instagram-webhook` forwards to this service's `/instagram/events`. Use either this callback or the direct backend callback. The bridge folder is an integration bundle, not a separate Next.js application.

## Tests

The deterministic suite uses mocked external services and temporary databases. It can run without a private `.env`:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Coverage includes Reel-to-order chat, enrollment resumption, ownership, replay/stale buttons, quote expiry, budgets, duplicate checkout prevention, profile isolation, sensitive input handling, inventory confirmation, recipe follow-ups, and opt-in add-ons.

Live sandbox checks use real OpenAI/Reap calls, capture outgoing DMs, and use temporary test state:

```sh
mkdir -p work
.venv/bin/python -u -m scripts.instagram_personal_e2e
.venv/bin/python -u -m scripts.instagram_e2e
```

The commerce live check additionally requires a locally supplied `work/test-product-reel.mp4` fixture. These checks require populated credentials and a sandbox enrollment. A payment approval URL is not evidence of a completed payment: hosted approval must complete before the bot reports an order.
