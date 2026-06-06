"""
tracking.py — credibility plumbing on top of db.get_store().

Pure helpers (make_report_id, confidence_from) stay dependency-free.
Everything else writes through the store, so it persists in Supabase when
configured and degrades to the local fallback otherwise. No fake data is ever
synthesised; reads return whatever is really there.
"""
from __future__ import annotations
import re
import uuid
from datetime import date

import db

APP_VERSION = "candor-v1-wave2"
LEDGER_MIN_OUTCOMES = 50          # public calibration gate
LEDGER_MIN_PER_BUCKET = 10


# ----------------------------------------------------------------- pure helpers
def make_report_id() -> str:
    return f"CND-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"


def confidence_from(meta: dict) -> str:
    n = (meta or {}).get("n_days", 0)
    return "High" if n >= 30 else ("Medium" if n >= 15 else "Low")


def valid_email(email: str) -> bool:
    email = (email or "").strip()
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


# ----------------------------------------------------------------- writes
def log_report(full: dict, market_type: str, payment_status: str, is_demo: bool) -> None:
    rows = full.get("firm_rows", [])
    worst = rows[-1] if rows else {}
    best = rows[0] if rows else {}
    db.get_store().insert("reports", {
        "report_id": full.get("report_id"),
        "created_at": db.now_iso(),
        "email": None,
        "payment_status": payment_status,
        "is_demo": bool(is_demo),
        "market_type": market_type,
        "selected_firm_filter": market_type,
        "best_firm": full.get("best_firm"),
        "best_pass_odds": round(float(full.get("best_pass_prob", 0)), 4),
        "worst_firm": worst.get("firm"),
        "worst_pass_odds": round(float(worst.get("pass_prob", 0)), 4),
        "killer_rule": full.get("best_killer_rule"),
        "verdict": (best.get("verdict") or "").upper(),
        "confidence": full.get("confidence"),
        "ruleset_version": full.get("ruleset_version"),
        "simulation_date": full.get("simulation_date"),
        "pdf_downloaded": False,
        "source_app_version": APP_VERSION,
    })


def log_lead(email: str, report_id: str, source: str = "report", consent: bool = True) -> bool:
    if not valid_email(email):
        return False
    db.get_store().insert("leads", {
        "email": email.strip(), "created_at": db.now_iso(),
        "source": source, "report_id": report_id, "consent": bool(consent),
    })
    return True


def log_pdf_download(report_id: str) -> None:
    log_admin_event("pdf_download", report_id=report_id)


def log_watchtower_signup(email: str, report_id: str, ruleset_version: str,
                          firm_interest: str | None = None) -> bool:
    if not valid_email(email):
        return False
    db.get_store().insert("watchtower_waitlist", {
        "email": email.strip(), "report_id": report_id, "created_at": db.now_iso(),
        "firm_interest": firm_interest, "ruleset_version": ruleset_version,
        "notified": False,
    })
    return True


def log_outcome(payload: dict) -> bool:
    row = {"outcome_id": uuid.uuid4().hex, "submitted_at": db.now_iso()}
    row.update(payload)
    db.get_store().insert("outcomes", row)
    log_admin_event("outcome_submitted", report_id=payload.get("report_id"))
    return True


def log_signal_scan(payload: dict) -> None:
    row = {"scan_id": uuid.uuid4().hex, "created_at": db.now_iso()}
    row.update(payload)
    db.get_store().insert("signal_scans", row)


def log_admin_event(event_type: str, report_id=None, email=None, metadata=None) -> None:
    db.get_store().insert("admin_events", {
        "event_id": uuid.uuid4().hex, "created_at": db.now_iso(),
        "event_type": event_type, "report_id": report_id, "email": email,
        "metadata": metadata,
    })


# ----------------------------------------------------------------- reads
def ledger_public_stats() -> dict:
    s = db.get_store()
    total = s.count("outcomes")
    return {
        "total_outcomes": total,
        "min_required": LEDGER_MIN_OUTCOMES,
        "ready": total >= LEDGER_MIN_OUTCOMES,
        "backend": s.backend,
    }


def _tally(rows, key):
    out = {}
    for r in rows:
        v = r.get(key) or "—"
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))


def admin_stats() -> dict:
    s = db.get_store()
    reports = s.select("reports", select="*", limit=5000)
    return {
        "backend": s.backend,
        "total_reports": len(reports),
        "real_reports": sum(1 for r in reports if not r.get("is_demo")),
        "leads": s.count("leads"),
        "pdf_downloads": s.count("admin_events", {"event_type": "pdf_download"}),
        "watchtower": s.count("watchtower_waitlist"),
        "outcomes": s.count("outcomes"),
        "signal_scans": s.count("signal_scans"),
        "killer_rule_dist": _tally(reports, "killer_rule"),
        "best_firm_dist": _tally(reports, "best_firm"),
        "payment_dist": _tally(reports, "payment_status"),
        "recent": sorted(reports, key=lambda r: r.get("created_at") or "",
                         reverse=True)[:10],
    }
