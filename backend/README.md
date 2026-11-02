# BotFarmHQ backend starter

New files only. This does **not** overwrite the landing page, chat UI,
admin page, sign-in, sign-up, README, or SYNC files, and it is **not**
pushed to GitHub and **not** deployed to production.

## What is in here

- `server.py` — Python standard library only. No external packages.
  No API keys. No passwords. No real client data.
- `bots.json` — COO Bot plus Front Desk, Quotes, After Hours, Reviews.
  Each bot has 3–5 fixed FAQ answers. No free-form model generation.
- `data/` — created at runtime. Booking requests and leads are stored
  here as local JSON only. This folder is a local store, not a database
  and not a production system.

## Locked facts used

- Plans: Basic $349/mo (8 bots), Plus $799/mo (25 bots),
  Enterprise $1,999/mo (50 bots). Farm cap: 50 bots.
- Weekly limits: Basic 2,500, Plus 10,000, Enterprise 25,000 messages.
- Tokens: from $50+, 15x usage (for example 1,000 a week becomes 15,000).
- Offered by Main Street Media HQ, Powered by botfarmhq.com.
- Control: talk through the COO Bot only, in plain words.

## How to run it locally

```bash
cd ~/workspace/botfarmhq
python3 backend/server.py
# listens on http://127.0.0.1:8000
# or: BOTFARMHQ_PORT=8001 python3 backend/server.py
```

Try it:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/vm/status
curl http://127.0.0.1:8000/api/usage
curl -N -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"bot":"coo","message":"check usage"}'
curl -X POST http://127.0.0.1:8000/api/book \
  -H 'Content-Type: application/json' \
  -d '{"name":"Test Person","phone":"555-000-0000","job":"Leaking sink","bot":"front"}'
curl -X POST http://127.0.0.1:8000/api/leads \
  -H 'Content-Type: application/json' \
  -d '{"name":"Test Person","phone":"555-000-0000","message":"Need a quote","bot":"quotes"}'
```

Notes on the API:

- `POST /api/chat` streams server-sent events, one word per event,
  then a final event with the HTML card and `done: true`.
  It matches a fixed FAQ by keyword. If nothing matches, it falls back
  to a human handoff message. It never generates code.
- `GET /api/vm/status` and `GET /api/usage` read the local JSON store.
  Usage counts chat replies only. Token counts are a rough estimate
  (about 4 characters per token) and are **not** a bill.
- `POST /api/book` creates a booking **REQUEST** record. The record
  itself is labelled `REQUEST — not a real calendar write`.
- `POST /api/leads` creates a lead record. Both record endpoints
  refuse text that looks like health details (Path A guard).

## How to deploy it to Brian's 8GB VM (steps only)

No host, user, key, or password is invented here. Brian supplies those
himself, on his own machine, and this starter is copied to the VM by
whoever owns the VM.

1. On the VM, install Python 3 (standard library only, no pip packages).
2. Copy the whole `backend/` folder to the VM, keeping `server.py`,
   `bots.json`, and an empty `data/` folder together.
3. Start it as a service that restarts on boot (for example systemd
   on Linux, or the VM host's own service manager). Bind it to
   localhost and put a reverse proxy in front of it if it must face
   the internet — do not expose port 8000 directly.
4. Point the chat UI at the deployed `/api/chat` URL, replacing the
   simulated streaming in the prototype. Keep the same FAQ contract.
5. Back up `backend/data/` regularly, and rotate it on a written
   retention rule before any client data is stored there.
6. Before any live client traffic: finish the stubs below, and pass
   the compliance gates below. Until then, keep this as a local
   starter and a demo, not a production service.

## What is REAL vs what is still a STUB

Real in this starter:

- FAQ matching, word-by-word SSE streaming, and HTML card output.
- COO Bot farm-control answers (add a bot, check usage, buy tokens,
  view VM) in plain words.
- Local booking-request and lead records, with a Path A refusal
  for health-detail text.
- Local usage and VM-status reporting from the JSON store.

Still a STUB — do not claim these work:

- Real calendar write (Google, Outlook, Jobber, Housecall).
  `/api/book` is a request only, confirmed by a human.
- Real connectors (Google Business, Facebook, Instagram, TikTok,
  GoHighLevel, Retell). Connector buttons in the prototype are sample.
- Real Stripe billing and token wallets. Prices are published, but
  no payment is taken here.
- Real secure auth. The Pages sign-in/sign-up pages are browser-local
  demo only. This server has no login, no password check, and no
  session store. Do not put client data behind it as-is.
- Real VM agent. `/api/vm/status` reports the local store, not a
  live agent on Brian's VM.
- Real review posting. Reviews are never invented and never posted
  automatically here.

## Compliance gates (do not skip these before live use)

- **Path A non-PHI only.** No patient health details in chat, forms,
  bookings, or leads. The server refuses health-detail text, but that
  guard is a safety net, not HIPAA compliance.
- **No HIPAA claim.** Do not say HIPAA compliant, certified, or ready.
  A HIPAA top tier needs, at minimum: a signed BAA, vendor BAAs,
  a written risk analysis, named Security and Privacy Officers,
  encryption, MFA, audit logging, a tested restore, a breach plan,
  training records, and attorney review. None of that is in this starter.
- **AI disclosure.** Every bot must say it is an automated assistant,
  not a human. The COO Bot FAQ does this; keep it in every bot.
- **Opt-out.** A lead or booking with `opt_out: true` means stop
  contacting that person on all channels, the same day.
- **No invented data.** No invented prices, reviews, testimonials,
  hours, or clients. The only accounts in the demo are Brian as admin
  and the labelled Smith Plumbing test dummy client.
- **No passwords.** Never hardcode a password, API key, or token in
  this folder, and never ask a user for a password in chat.
- **Attorney review.** Terms, Privacy, and any BAA need attorney review
  before a first live client, especially a dental or med spa client.

## Office-bot scope — hard limit

This backend answers FAQs, takes booking requests, takes quote
requests, and captures leads, and it outputs short text plus a simple
HTML card. It does **not** generate code, build apps, or do Grok
build-like work. If a request needs code generation, refuse it and
hand it to a human.


## Weekly usage bar, $10/day cap, and compute-first routing (2026-11-02)

Adapted from the McDonoughHQ usage update, adapted — not copied — because
this backend has no model call yet:

- Admin page (`admin.html`, Usage section) shows the weekly total, today's
  total, daily $10 cap progress, per-bot usage, and the top bot first, in
  words and numbers, never color alone.
- The admin page reads `GET /api/usage`. If the backend is not running,
  it says plainly "No live usage yet — backend not deployed" and shows no
  invented numbers. The chat demo's sample numbers are demo only and are
  never used as usage data.
- Daily cap: `DAILY_BOT_SPEND_CAP_USD`, default $10, all bots combined.
  Invalid, missing, or negative values fall back to $10, never unlimited.
  The cap gates real API spend. FAQ replies use $0 API spend, so the cap
  is dormant until a real model call is wired. When reached, chat answers
  "Daily $10 cap reached, resumes tomorrow." — never a generic failure.
- Compute-first, right model for the job, COGS low but quality high:
  VM-local compute, templates, and cache FIRST, before any AI API call.
  FAQ, greeting, help, and status answers come from fixed templates on
  the VM, with no AI model call ($0 API spend). Simple tasks use a
  cheap/small model only. Builder-level work uses the ADVANCED model,
  and quality there must NOT be cut to save a few cents — do NOT route
  everything to cheapest. There is no Builder bot in this farm, so office
  bots do NOT run builder work themselves and do NOT downgrade it to
  cheap: they hand it to a Builder / human on the advanced model.
- Tokens are a rough estimate (about 4 characters per token), not a bill.
  Estimated cost uses the cheapest listed output rate ($2 per 1M tokens)
  and is labelled an estimate everywhere.

GitHub Pages is static and cannot run this backend. Pushing `backend/` to
the repo stores the code for VM deployment; it does not make the Pages
site live. Deploy to Brian's VM only with his separate go and host details.
