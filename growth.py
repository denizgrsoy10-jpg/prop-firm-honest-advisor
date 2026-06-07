"""
Candor Growth Autopilot V1 — internal marketing tooling.

SAFETY CONTRACT (do not weaken):
- No spam, no browser automation, no unofficial APIs.
- X / Instagram / YouTube  -> queue + MOCK publish only. Real official API
  later via ENV keys (X_API_KEY, META_ACCESS_TOKEN, YOUTUBE_CLIENT_ID,
  YOUTUBE_CLIENT_SECRET). Until then everything is a dry-run log.
- Reddit / Discord / Telegram -> scout + draft + approval ONLY. Never auto-post.
- Compliance Guard blocks risky copy from ever being 'approved'.
- Draft content can never be auto-published.
- This module never touches the engine / payment / report flow.

All persistence goes through db.get_store() (Supabase when configured, else
local ephemeral). Every function fails soft: returns False/[]/{} on error,
never raises into the UI.
"""

import uuid
import time
import urllib.parse

import db


# ----------------------------------------------------------------------------
# Constants: compliance, channels, templates
# ----------------------------------------------------------------------------

BANNED_PHRASES = [
    "guaranteed pass",
    "get funded",
    "make money",
    "profit guaranteed",
    "guaranteed payout",
    "guaranteed profit",
    "trading advice",
    "investment advice",
    "financial advice",
    "risk free",
    "risk-free",
    "easy money",
    "double your",
    "can't lose",
    "cant lose",
    "sure thing",
    "100% win",
]

SAFE_LANGUAGE = [
    "No guarantees.",
    "No signals.",
    "Statistical simulation only.",
    "Before you pay, run the math.",
    "We show the odds, not promises.",
    "Not financial advice.",
]

# Channel default modes. The safety contract lives here.
#   auto      -> may publish approved content automatically (ONLY once a real
#                official API key is present; until then it still mocks)
#   approval  -> drafts, waits for a human to publish
#   scout     -> finds opportunities + drafts, NEVER posts
#   locked    -> does nothing
CHANNEL_DEFAULTS = {
    "x":          {"mode": "approval", "api_ready": False, "label": "X / Twitter"},
    "instagram":  {"mode": "approval", "api_ready": False, "label": "Instagram / Reels"},
    "youtube":    {"mode": "approval", "api_ready": False, "label": "YouTube Shorts"},
    "linkedin":   {"mode": "approval", "api_ready": False, "label": "LinkedIn"},
    "reddit":     {"mode": "scout",    "api_ready": False, "label": "Reddit"},
    "discord":    {"mode": "approval", "api_ready": False, "label": "Discord"},
    "telegram":   {"mode": "approval", "api_ready": False, "label": "Telegram"},
    "paid_ads":   {"mode": "approval", "api_ready": False, "label": "Paid Ads"},
}

CONTENT_TYPES = [
    "x_post", "thread", "reddit_post", "video_script",
    "influencer_dm", "seo_intro", "reels_caption",
]

# Ready-to-customize templates. These are intentionally on-brand and compliant.
TEMPLATES = {
    "x_post": (
        "Most traders ask: \"Which prop firm is best?\"\n\n"
        "Wrong question.\n\n"
        "The real one: \"Which firm can my trading behavior survive?\"\n\n"
        "Candor checks pass odds, the killer rule, and fee burn.\n"
        "No guarantees. No signals. Just the math."
    ),
    "thread": (
        "1/ Same trade history. Six prop firms. Wildly different odds.\n\n"
        "2/ Apex: 69.9%. E8: 32.0%. FTMO 2-Step: 1.6%.\n\n"
        "3/ The difference isn't the trader. It's the rules.\n\n"
        "4/ Candor runs your real history against verified rulesets and shows "
        "the one rule most likely to end your run.\n\n"
        "5/ No guarantees. No signals. Run the math before you pay."
    ),
    "reddit_post": (
        "I ran the same trade history through 6 prop-firm rulesets.\n\n"
        "Apex: 69.9% | E8: 32.0% | FTMO 2-Step: 1.6%\n\n"
        "Same trader, same history, very different outcomes. The cheapest or "
        "most famous firm isn't always the one your behavior can survive.\n\n"
        "Posting the method, not a pitch — happy to discuss the math."
    ),
    "video_script": (
        "[0-3s]  Same trade history.\n"
        "[3-7s]  Apex 69.9% / E8 32.0% / FTMO 1.6%\n"
        "[7-12s] Rules matter more than skill here.\n"
        "[12-15s] Candor: run the math before you pay. No guarantees."
    ),
    "influencer_dm": (
        "Hi {name} — I built Candor, an honest prop-firm reality check: it "
        "replays a trader's real history against verified firm rules and shows "
        "pass odds, the killer rule, and fee burn. No guarantees, no signals. "
        "Thought it might fit your {niche} audience — open to sharing a free "
        "breakdown if useful?"
    ),
    "seo_intro": (
        "Before paying a prop-firm challenge fee, most traders never check "
        "whether their own trading behavior can survive that firm's rules. "
        "This page breaks down how pass odds, trailing drawdown, and fee burn "
        "actually interact — using verified rulesets, not marketing claims."
    ),
    "reels_caption": (
        "Same trader. Different firm. 69.9% vs 1.6%.\n"
        "The rules decide more than you think.\n"
        "Run the math before you pay. #propfirm #trading"
    ),
}

DAILY_PLAN_TEMPLATE = [
    {"task": "Publish 2 X posts",            "channel": "x",         "count": 2},
    {"task": "Publish 1 short video",        "channel": "youtube",   "count": 1},
    {"task": "Send 10 influencer DMs",       "channel": "influencer","count": 10},
    {"task": "Run 1 Reddit scout batch",     "channel": "reddit",    "count": 1},
    {"task": "Draft 1 SEO page",             "channel": "seo",       "count": 1},
]


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _now():
    return db.now_iso()


# ----------------------------------------------------------------------------
# Compliance Guard
# ----------------------------------------------------------------------------

def check_compliance(text: str) -> dict:
    """Return {'status': 'clean'|'risky', 'flags': [...], 'suggestions': [...]}.

    'risky' content can never be approved or scheduled. Pure function; no I/O.
    """
    if not text:
        return {"status": "clean", "flags": [], "suggestions": []}
    low = text.lower()
    flags = [p for p in BANNED_PHRASES if p in low]
    status = "risky" if flags else "clean"
    suggestions = SAFE_LANGUAGE if flags else []
    return {"status": status, "flags": flags, "suggestions": suggestions}


# ----------------------------------------------------------------------------
# Approved Content Vault
# ----------------------------------------------------------------------------

def add_content(content_type, title, body, hook="", cta="") -> dict:
    """Create a draft content item. Always starts as draft; compliance is
    computed and stored. Returns the row dict (also persisted)."""
    comp = check_compliance(" ".join([title or "", hook or "", body or "", cta or ""]))
    row = {
        "content_id": _id("cnt"),
        "type": content_type if content_type in CONTENT_TYPES else "x_post",
        "title": title or "",
        "body": body or "",
        "hook": hook or "",
        "cta": cta or "",
        "status": "draft",
        "compliance_status": comp["status"],
        "compliance_flags": ", ".join(comp["flags"]),
        "created_at": _now(),
        "updated_at": _now(),
    }
    try:
        db.get_store().insert("growth_content", row)
    except Exception:
        pass
    return row


def approve_content(content_id: str) -> dict:
    """Approve a content item — but ONLY if compliance is clean.

    Returns {'ok': bool, 'reason': str}. Risky copy is refused here; this is the
    hard gate the safety contract depends on.
    """
    store = db.get_store()
    rows = store.select("growth_content", filters={"content_id": content_id})
    if not rows:
        return {"ok": False, "reason": "Content not found."}
    item = rows[0]
    if item.get("compliance_status") == "risky":
        return {"ok": False,
                "reason": "Blocked by Compliance Guard — contains risky language. "
                          "Rewrite using safe Candor wording before approving."}
    # We can't UPDATE via the minimal REST client, so we re-insert a status event
    # in the publish log and rely on the vault's latest-status read. To keep V1
    # simple and append-only, we log an approval event.
    _log_publish(content_id, channel="vault", action="approved", post_url="", utm="")
    return {"ok": True, "reason": "Approved."}


def list_content(status=None, limit=200):
    store = db.get_store()
    f = {"status": status} if status else None
    try:
        rows = store.select("growth_content", filters=f, order="created_at.desc", limit=limit)
    except Exception:
        rows = []
    # overlay approval events (append-only status model)
    approved = _approved_ids()
    for r in rows:
        if r.get("content_id") in approved and r.get("status") == "draft":
            r["status"] = "approved"
    return rows


def _approved_ids():
    try:
        logs = db.get_store().select("growth_publish_log",
                                     filters={"action": "approved"}, limit=1000)
        return {l.get("content_id") for l in logs}
    except Exception:
        return set()


def vault_counts():
    rows = list_content(limit=1000)
    out = {"total": len(rows), "draft": 0, "approved": 0,
           "scheduled": 0, "published": 0, "risky": 0}
    for r in rows:
        st = r.get("status", "draft")
        if st in out:
            out[st] += 1
        if r.get("compliance_status") == "risky":
            out["risky"] += 1
    return out


# ----------------------------------------------------------------------------
# Timezone Scheduler
# ----------------------------------------------------------------------------

REGION_OFFSETS = {"EU": 1, "US": -5, "Asia": 8}  # rough display offsets only


def schedule_content(content_id, channel, region, scheduled_time_utc, mode="approval") -> dict:
    """Queue a content item on a channel. Refuses if content is not approved or
    is risky. Sets status by channel mode."""
    rows = db.get_store().select("growth_content", filters={"content_id": content_id})
    if not rows:
        return {"ok": False, "reason": "Content not found."}
    item = rows[0]
    if item.get("compliance_status") == "risky":
        return {"ok": False, "reason": "Risky content can't be scheduled."}
    if content_id not in _approved_ids() and item.get("status") != "approved":
        return {"ok": False, "reason": "Only approved content can be scheduled."}

    ch = channel if channel in CHANNEL_DEFAULTS else "x"
    eff_mode = mode or CHANNEL_DEFAULTS[ch]["mode"]
    row = {
        "schedule_id": _id("sch"),
        "content_id": content_id,
        "channel": ch,
        "region": region if region in REGION_OFFSETS else "EU",
        "scheduled_time_utc": scheduled_time_utc,
        "status": "queued",
        "mode": eff_mode,
        "created_at": _now(),
    }
    try:
        db.get_store().insert("growth_schedule", row)
    except Exception:
        pass
    return {"ok": True, "reason": "Queued.", "row": row}


def list_schedule(limit=200):
    try:
        return db.get_store().select("growth_schedule",
                                     order="scheduled_time_utc.asc", limit=limit)
    except Exception:
        return []


# ----------------------------------------------------------------------------
# UTM Generator
# ----------------------------------------------------------------------------

BASE_URL = "https://prop-firm-honest-advisor-u4r6drscbs7qrdfk5jqmea.streamlit.app"


def make_utm(source, medium, campaign, content="") -> dict:
    params = {
        "utm_source": source or "candor",
        "utm_medium": medium or "social",
        "utm_campaign": campaign or "realitycheck",
    }
    if content:
        params["utm_content"] = content
    link = BASE_URL + "/?" + urllib.parse.urlencode(params)
    row = {
        "utm_id": _id("utm"),
        "link": link,
        "utm_source": params["utm_source"],
        "utm_medium": params["utm_medium"],
        "utm_campaign": params["utm_campaign"],
        "utm_content": content,
        "created_at": _now(),
    }
    try:
        db.get_store().insert("growth_utm_links", row)
    except Exception:
        pass
    return row


# ----------------------------------------------------------------------------
# Influencer DM Queue
# ----------------------------------------------------------------------------

def add_influencer(name, platform, profile_url, niche, message="", notes="") -> dict:
    row = {
        "influencer_id": _id("inf"),
        "name": name or "",
        "platform": platform or "",
        "profile_url": profile_url or "",
        "niche": niche or "",
        "message": message or "",
        "status": "queued",
        "last_contacted": "",
        "reply_status": "none",
        "notes": notes or "",
        "created_at": _now(),
    }
    try:
        db.get_store().insert("growth_influencers", row)
    except Exception:
        pass
    return row


def list_influencers(limit=200):
    try:
        return db.get_store().select("growth_influencers",
                                     order="created_at.desc", limit=limit)
    except Exception:
        return []


# ----------------------------------------------------------------------------
# Reddit Scout  (draft only — NEVER posts)
# ----------------------------------------------------------------------------

def add_reddit_scout(subreddit, post_idea, reply_draft="") -> dict:
    """Stores a Reddit opportunity + draft. Scores self-promo risk. This NEVER
    posts to Reddit — it only drafts for human approval."""
    text = " ".join([post_idea or "", reply_draft or ""])
    comp = check_compliance(text)
    # crude self-promo risk: links + promo words raise the score
    low = text.lower()
    risk = 0
    for token in ["http", "candor", "my tool", "i built", "check out", "sign up", "link"]:
        if token in low:
            risk += 1
    risk_label = "Low" if risk <= 1 else ("Medium" if risk <= 3 else "High")
    row = {
        "scout_id": _id("rdt"),
        "subreddit": subreddit or "",
        "post_idea": post_idea or "",
        "reply_draft": reply_draft or "",
        "self_promo_risk": risk_label,
        "compliance_status": comp["status"],
        "status": "draft",          # always draft; approval required to act
        "approval_required": True,
        "created_at": _now(),
    }
    try:
        db.get_store().insert("growth_reddit_scout", row)
    except Exception:
        pass
    return row


def list_reddit_scout(limit=200):
    try:
        return db.get_store().select("growth_reddit_scout",
                                     order="created_at.desc", limit=limit)
    except Exception:
        return []


# ----------------------------------------------------------------------------
# Daily Attack Plan
# ----------------------------------------------------------------------------

def generate_daily_plan() -> list:
    """Return today's task list. Idempotent-ish: tasks are templated, not random."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    plan = []
    for t in DAILY_PLAN_TEMPLATE:
        plan.append({
            "task_id": _id("tsk"),
            "date": today,
            "task": t["task"],
            "channel": t["channel"],
            "count": t["count"],
            "status": "todo",
            "created_at": _now(),
        })
    # persist (append-only log of plans)
    try:
        store = db.get_store()
        for p in plan:
            store.insert("growth_tasks", p)
    except Exception:
        pass
    return plan


# ----------------------------------------------------------------------------
# Mock publish adapters  (NO real network posting)
# ----------------------------------------------------------------------------

def _real_api_present(channel) -> bool:
    """True only if an official API credential is actually set in env."""
    keymap = {
        "x": "X_API_KEY",
        "instagram": "META_ACCESS_TOKEN",
        "youtube": "YOUTUBE_CLIENT_ID",
    }
    key = keymap.get(channel)
    if not key:
        return False
    return bool(db._env(key))


def _log_publish(content_id, channel, action, post_url="", utm=""):
    row = {
        "log_id": _id("log"),
        "content_id": content_id,
        "channel": channel,
        "action": action,            # mock_publish / approved / scheduled
        "post_url": post_url,
        "utm_link": utm,
        "published_at": _now(),
    }
    try:
        db.get_store().insert("growth_publish_log", row)
    except Exception:
        pass
    return row


def publish_x_mock(content_id, utm="") -> dict:
    return _mock_publish("x", content_id, utm)


def publish_instagram_mock(content_id, utm="") -> dict:
    return _mock_publish("instagram", content_id, utm)


def publish_youtube_mock(content_id, utm="") -> dict:
    return _mock_publish("youtube", content_id, utm)


def _mock_publish(channel, content_id, utm="") -> dict:
    """Dry-run 'publish'. Refuses non-approved content. Writes a publish log
    entry with a fake URL so the pipeline is observable end-to-end.

    When a real official API key is later present, this is where the live
    adapter call would go — for now it stays a mock regardless, by contract.
    """
    if content_id not in _approved_ids():
        rows = db.get_store().select("growth_content", filters={"content_id": content_id})
        if not rows or rows[0].get("status") != "approved":
            return {"ok": False, "reason": "Only approved content can be published."}
    mode = "live" if _real_api_present(channel) else "mock"
    fake_url = f"https://{channel}.example/mock/{uuid.uuid4().hex[:8]}"
    log = _log_publish(content_id, channel, f"{mode}_publish", post_url=fake_url, utm=utm)
    return {"ok": True, "mode": mode, "post_url": fake_url, "log": log}


def list_publish_log(limit=200):
    try:
        return db.get_store().select("growth_publish_log",
                                     order="published_at.desc", limit=limit)
    except Exception:
        return []


# ----------------------------------------------------------------------------
# Channel modes (read-only defaults in V1; persisted view)
# ----------------------------------------------------------------------------

def channel_modes() -> list:
    out = []
    for key, cfg in CHANNEL_DEFAULTS.items():
        live = _real_api_present(key)
        out.append({
            "channel": key,
            "label": cfg["label"],
            "mode": cfg["mode"],
            "api_ready": live,
            "publishes": "live" if live and cfg["mode"] == "auto" else
                         ("mock" if cfg["mode"] in ("auto", "approval") else "never"),
        })
    return out


# ----------------------------------------------------------------------------
# Dashboard rollup
# ----------------------------------------------------------------------------

def autopilot_overview() -> dict:
    counts = vault_counts()
    sched = list_schedule(limit=1000)
    next24 = [s for s in sched if s.get("status") == "queued"]
    return {
        "vault": counts,
        "scheduled_total": len(sched),
        "queued": len(next24),
        "next24": next24[:20],
        "influencers": len(list_influencers(limit=1000)),
        "reddit_scout": len(list_reddit_scout(limit=1000)),
        "publish_log": len(list_publish_log(limit=1000)),
        "channels": channel_modes(),
    }
