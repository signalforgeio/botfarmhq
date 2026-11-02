#!/usr/bin/env python3
"""
BotFarmHQ backend starter — Python standard library only.

What this IS:
  A small office-bot server. It answers FAQs from bots.json, streams
  replies word by word, records booking REQUESTS and leads in local JSON,
  and reports VM / usage from a local JSON store.

What this is NOT (stubs, do not claim otherwise):
  - No real calendar write. /api/book creates a REQUEST record only.
  - No real connectors (Google Business, Facebook, Instagram, TikTok,
    GoHighLevel, Retell). Connector buttons in the prototype are sample only.
  - No Stripe billing. Tokens from $50+ are a price, not a live payment.
  - No secure server-side auth. The Pages sign-in/sign-up pages are
    browser-local demo only. Do not use a real password with this server.
  - No HIPAA handling. Path A non-PHI only. No HIPAA claim.

Compliance gates baked in:
  - Every reply is from a fixed FAQ in bots.json. No code generation.
  - The server never invents prices, reviews, testimonials, or hours.
  - Bot replies identify as an automated assistant in the COO bot FAQ.
  - Booking and lead records include an opt_out flag defaulting to False;
    setting opt_out=true means stop contacting that person on all channels.
  - PHI is refused: if a message looks like it contains health details,
    the server returns a Path A deflection instead of storing it.

Run:
  python3 backend/server.py            # listens on http://127.0.0.1:8000
  BOTFARMHQ_PORT=8001 python3 backend/server.py

Weekly usage bar, $10/day cap, and model routing (adapted from McDonoughHQ,
adapted — not copied — because this backend has no model call yet):
  - GET /api/usage reports weekly messages/tokens, today, the $10/day cap,
    per-bot usage sorted by estimated cost, and the top bot first.
  - Daily cap: DAILY_BOT_SPEND_CAP_USD, default $10, all bots combined.
    Invalid / missing / negative values fall back to $10, never unlimited.
    The cap gates real API spend. FAQ replies use $0 API spend, so the cap
    is dormant until a real model call is wired; it is not a fake block.
    When the cap is reached, chat answers with exactly:
    "Daily $10 cap reached, resumes tomorrow." — never a generic failure.
  - Compute-first: FAQ, greeting, help, and status answers are answered
    from fixed templates on the VM, with no AI model call at all.
    Simple tasks stay local. Code / build requests are OUT OF SCOPE for
    these office bots: they are refused with a human handoff, never sent
    to an advanced model. There is no Builder bot in this farm, so no bot
    here may silently upgrade to an advanced model. If a real model is
    added later, simple tasks must use the cheapest model, and advanced
    work must be Builder-only, with this cap check first.
  - Token counts are a rough estimate (about 4 characters per token),
    not a bill. Estimated cost uses the cheapest listed output rate
    ($2 per 1M tokens) and is labelled an estimate everywhere it appears.
"""
import html
import json
import os
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
try:
    from zoneinfo import ZoneInfo
except ImportError:  # very old Python
    ZoneInfo = None


BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
BOTS_PATH = os.path.join(BASE, "bots.json")

with open(BOTS_PATH, encoding="utf-8") as f:
    CATALOG = json.load(f)

BOTS = {b["id"]: b for b in CATALOG["bots"]}
FARM = CATALOG["farm"]
WEEKLY_LIMITS = FARM["weekly_limits"]

# --- Weekly usage bar / $10/day cap / compute-first routing ---
# Adapted from McDonoughHQ usage.mjs. No secret lives here.
DAILY_CAP_ENV = "DAILY_BOT_SPEND_CAP_USD"
DAILY_CAP_DEFAULT_USD = 10.0
# Cheapest listed output rate, used ONLY for the labelled estimate.
CHEAP_OUTPUT_USD_PER_TOKEN = 2.0 / 1_000_000
CAP_MESSAGE = "Daily $10 cap reached, resumes tomorrow."

def daily_cap_usd(env=None):
    """Daily all-bots cap in USD. Falls back to $10, never unlimited."""
    if env is None:
        env = os.environ
    try:
        raw = float(env.get(DAILY_CAP_ENV, ""))
    except (TypeError, ValueError):
        return DAILY_CAP_DEFAULT_USD
    if raw != raw or raw < 0:  # NaN or negative
        return DAILY_CAP_DEFAULT_USD
    return min(raw, 100.0)

def _today_str():
    import datetime
    if ZoneInfo is not None:
        try:
            return datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        except Exception:
            pass
    return datetime.date.today().isoformat()

def _monday_str():
    import datetime
    if ZoneInfo is not None:
        try:
            d = datetime.datetime.now(ZoneInfo("America/New_York")).date()
        except Exception:
            d = datetime.date.today()
    else:
        d = datetime.date.today()
    return (d - datetime.timedelta(days=d.weekday())).isoformat()

def cap_reached(api_spend_usd, cap_usd=None):
    return float(api_spend_usd or 0) >= float(cap_usd if cap_usd is not None else daily_cap_usd())

def estimated_cost_usd(tokens):
    return round(float(tokens or 0) * CHEAP_OUTPUT_USD_PER_TOKEN, 4)

_SIMPLE_RE = re.compile(r"\b(hi|hello|hey|help|hours|price|quote|book|booking|appointment|lead|contact|usage|status|check usage|view vm|buy tokens|add a bot)\b", re.I)
_BUILD_RE = re.compile(r"\b(build|code|coding|refactor|deploy|implement|program|programming)\b|\b(write|create|make)\b.*\b(app|script|file|feature|website|program|code)\b|\bfix (the )?bug\b|\bpull request\b|```|\bfunction |\bclass |\bimport |\bexport ", re.I)

def route_task(message, bot_id=""):
    """Compute-first routing for BotFarmHQ office bots.

    Returns a dict, never a model call by itself:
    - local: answer from fixed FAQ templates, $0 API spend.
    - refused: code/build work is out of scope here, human handoff only.
    There is no Builder bot in this farm, so 'advanced' is never returned.
    """
    msg = str(message or "")
    if _BUILD_RE.search(msg):
        return {"mode": "refused", "model": "none — human handoff",
                "reason": "Code/build work is out of scope for BotFarmHQ office bots."}
    return {"mode": "local", "model": "none — FAQ template on the VM",
            "reason": "Simple task answered locally, before any AI model call."}

def _usage_defaults():
    return {"messages_this_week": 0, "tokens": 0, "per_bot": {},
            "week_start": _monday_str(),
            "today": {"date": _today_str(), "messages": 0, "tokens": 0, "api_spend_usd": 0.0}}


# Very small Path A guard: health-detail words that must not be stored.
# This is a safety net, not a medical classifier and not HIPAA compliance.
PHI_WORDS = [
    "diagnosis", "prescription", "symptom", "treatment for", "my condition",
    "blood pressure", "diabetes", "cancer", "pregnancy", "insurance id",
    "medical record", "health insurance number",
]
PHI_RE = re.compile("|".join(re.escape(w) for w in PHI_WORDS), re.I)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def usage_path():
    return os.path.join(DATA_DIR, "usage.json")


def get_usage():
    usage = load_json(usage_path(), {})
    defaults = _usage_defaults()
    for key, value in defaults.items():
        usage.setdefault(key, value)
    usage.setdefault("today", defaults["today"])
    return usage


def _reset_if_stale(usage):
    """Reset weekly / daily counters when the week or day has rolled over."""
    if usage.get("week_start") != _monday_str():
        usage["messages_this_week"] = 0
        usage["tokens"] = 0
        usage["per_bot"] = {}
        usage["week_start"] = _monday_str()
    today = usage.get("today") or {}
    if today.get("date") != _today_str():
        # New day: API spend resets. Weekly counters reset separately above.
        usage["today"] = {"date": _today_str(), "messages": 0, "tokens": 0, "api_spend_usd": 0.0}
    return usage


def bump_usage(bot_id, answer_text, api_spend_usd=0.0):
    """Record one reply. FAQ replies cost $0 API spend; api_spend_usd is
    only non-zero when a real model call is wired in later."""
    usage = _reset_if_stale(get_usage())
    tokens = max(1, len(answer_text) // 4)  # rough estimate, not a bill
    usage["messages_this_week"] += 1
    usage["tokens"] += tokens
    usage["today"]["messages"] += 1
    usage["today"]["tokens"] += tokens
    usage["today"]["api_spend_usd"] = round(float(usage["today"].get("api_spend_usd", 0.0)) + float(api_spend_usd or 0.0), 4)
    per = usage.setdefault("per_bot", {})
    entry = per.setdefault(bot_id, {"messages_this_week": 0, "tokens": 0, "estimated_cost_usd": 0.0})
    entry["messages_this_week"] += 1
    entry["tokens"] += tokens
    entry["estimated_cost_usd"] = estimated_cost_usd(entry["tokens"])
    save_json(usage_path(), usage)
    return usage


def usage_payload():
    """Payload for /api/usage and /api/vm/status. Top bot first, by estimate."""
    usage = get_usage()
    cap = daily_cap_usd()
    spent = float(usage.get("today", {}).get("api_spend_usd", 0.0))
    names = {b["id"]: b["name"] for b in CATALOG["bots"]}
    per = {}
    for bot_id, entry in (usage.get("per_bot") or {}).items():
        per[bot_id] = {"messages_this_week": entry.get("messages_this_week", 0),
                       "tokens": entry.get("tokens", 0),
                       "estimated_cost_usd": estimated_cost_usd(entry.get("tokens", 0))}
    ranked = sorted(per.items(), key=lambda kv: kv[1]["estimated_cost_usd"], reverse=True)
    top = None
    if ranked and ranked[0][1]["tokens"] > 0:
        top = {"id": ranked[0][0], "name": names.get(ranked[0][0], ranked[0][0]),
               "messages": ranked[0][1]["messages_this_week"],
               "tokens": ranked[0][1]["tokens"],
               "estimated_cost_usd": ranked[0][1]["estimated_cost_usd"]}
    return {"bots": len(BOTS), "farm_cap": FARM["cap_bots"],
            "messages_this_week": usage["messages_this_week"],
            "tokens": usage["tokens"], "week_start": usage.get("week_start"),
            "today": usage.get("today"), "per_bot": per, "bot_names": names,
            "top_bot": top, "daily_cap_usd": cap, "daily_spent_usd": spent,
            "daily_remaining_usd": round(max(0.0, cap - spent), 2),
            "cap_reached": cap_reached(spent, cap),
            "cap_message": CAP_MESSAGE if cap_reached(spent, cap) else "",
            "weekly_limits": WEEKLY_LIMITS,
            "note": "Tokens are a rough estimate (about 4 characters per token), not a bill. FAQ replies use $0 API spend."}


def match_faq(bot, message):
    text = message.lower()
    for faq in bot["faqs"]:
        for kw in faq["keywords"]:
            if kw.lower() in text:
                return faq
    return None


def fallback(bot, message):
    return {
        "answer": (
            "I am an automated assistant, not a human. I could not answer that "
            "from this bot's own answers. Leave your name and phone and a human "
            "will follow up, or ask me about hours, booking, a quote, or a review."
        ),
        "card": {"body": "Leave your name and phone for a human follow-up.", "title": "Talk to a human", "type": "action"},
        "question": "Fallback",
    }


def answer_for(bot_id, message):
    bot = BOTS.get(bot_id, BOTS["coo"])
    if PHI_RE.search(message):
        return {
            "answer": (
                "I cannot take health details in this chat. This is a non-PHI chat. "
                "Please call the business directly, or tell me only your name and phone "
                "and the general service you need, with no health details."
            ),
            "card": {"body": "No health details in chat. Call the business for anything health-related.", "title": "Non-PHI only", "type": "info"},
            "question": "Path A deflection",
        }
    faq = match_faq(bot, message)
    return faq or fallback(bot, message)


def safe_card(faq):
    card = faq.get("card") or {}
    # HTML card output only: title/body are escaped, never raw HTML from input.
    return {
        "body": html.escape(str(card.get("body", ""))),
        "title": html.escape(str(card.get("title", ""))),
        "type": str(card.get("type", "info")),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/health"):
            self.send_json({"ok": True, "service": "botfarmhq-backend-starter", "bots": sorted(BOTS), "farm_cap": FARM["cap_bots"]})
        elif path == "/api/vm/status":
            payload = usage_payload()
            payload["status"] = "Running"
            payload["vm"] = "8GB VM (starter reports the local store; a live VM agent is still a stub)"
            self.send_json(payload)
        elif path == "/api/usage":
            self.send_json(usage_payload())
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/chat":
            self.handle_chat()
        elif path == "/api/book":
            self.handle_record("bookings.json", "booking_request")
        elif path == "/api/leads":
            self.handle_record("leads.json", "lead")
        else:
            self.send_json({"error": "not found"}, 404)

    def handle_chat(self):
        body = self.read_json()
        bot_id = str(body.get("bot", "coo"))
        message = str(body.get("message", "")).strip()
        if not message:
            self.send_json({"error": "message is required"}, 400)
            return
        # $10/day cap gate first: never a generic failure, never a silent block.
        today_spend = float(get_usage().get("today", {}).get("api_spend_usd", 0.0))
        if cap_reached(today_spend):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for word in CAP_MESSAGE.split(" "):
                self.wfile.write(f"data: {json.dumps({'word': word})}\n\n".encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(f"data: {json.dumps({'card': {'body': 'Resumes tomorrow. Ask a human if you need it today.', 'title': 'Daily cap reached', 'type': 'info'}, 'done': True, 'cap_reached': True})}\n\n".encode("utf-8"))
            return
        routed = route_task(message, bot_id)
        if routed["mode"] == "refused":
            faq = {"answer": "I cannot build code or apps here. These are office bots for answers, quotes, bookings, and leads. Leave your name and phone and a human will follow up about the build work.",
                   "card": {"body": "Office bots only. A human follows up on build work.", "title": "Human handoff", "type": "action"}}
        else:
            faq = answer_for(bot_id, message)
        usage = bump_usage(bot_id if bot_id in BOTS else "coo", faq["answer"])
        # Server-sent-event streaming: one word per event, then [DONE].
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        words = faq["answer"].split(" ")
        for word in words:
            payload = json.dumps({"word": word})
            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.01)
        done = json.dumps({"card": safe_card(faq), "done": True, "messages_this_week": usage["messages_this_week"]})
        self.wfile.write(f"data: {done}\n\n".encode("utf-8"))

    def handle_record(self, filename, kind):
        body = self.read_json()
        # Path A: refuse to store anything that looks like health details.
        haystack = " ".join(str(v) for v in body.values())
        if PHI_RE.search(haystack):
            self.send_json({"error": "Non-PHI only: do not send health details in this record."}, 400)
            return
        path = os.path.join(DATA_DIR, filename)
        records = load_json(path, [])
        record = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,
            "opt_out": bool(body.get("opt_out", False)),
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if kind == "booking_request":
            record["status"] = "REQUEST — not a real calendar write"
            for key in ("name", "phone", "email", "job", "bot"):
                if body.get(key):
                    record[key] = str(body[key])
        else:
            for key in ("name", "phone", "email", "message", "bot"):
                if body.get(key):
                    record[key] = str(body[key])
        records.append(record)
        save_json(path, records)
        self.send_json(record, 201)


def main():
    port = int(os.environ.get("BOTFARMHQ_PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"BotFarmHQ backend starter on http://127.0.0.1:{port}")
    print("Endpoints: POST /api/chat (SSE), GET /api/vm/status, GET /api/usage, POST /api/book, POST /api/leads")
    server.serve_forever()


if __name__ == "__main__":
    main()
