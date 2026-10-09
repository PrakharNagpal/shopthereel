# Reel commerce showcase

Next.js website with a stationary central phone and horizontal scroll-driven scenery. Instagram feed, Telegram chat, TikTok video UI, product sharing, matching, size selection, Reap-style simulated checkout, and confirmation. Logos orbit and products pass behind the phone. New white-background product imagery included.

Run npm install, then npm run dev. Build with npm run build. Static output: out.

No live payments or commerce APIs connected. Instagram and Telegram flows are represented; TikTok is illustrative.

Build and TypeScript checks passed. Browser verified platform switching, matching, size persistence, checkout, confirmation, and stationary positioning.

Private preview: https://reel-commerce-motion.mellowbull8.chatgpt.site


## Local accounts and preferences

The login and account pages use a separate local account service and SQLite database.
No requests are made to the commerce backend, and saved account preferences do not
change the Telegram bot's profile or checkout settings.

Requires Node.js 22.13+ for the built-in SQLite module. Start in two terminals:

```sh
npm run accounts
npm run dev
```

Open http://127.0.0.1:3210/login, create an account, then edit its preferences.
Passwords require at least 10 characters and are stored as salted scrypt hashes.
Sessions use HttpOnly cookies. The private database is in `.account-data/` and ignored by Git.
The account service listens on loopback port 3211; this account feature is local only.
The existing static website and illustrative checkout remain separate.

Verification:

```sh
node auth/test.mjs
node node_modules/typescript/bin/tsc --noEmit
```
