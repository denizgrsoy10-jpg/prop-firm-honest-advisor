"""
tracking.py
-----------
Lightweight sales/credibility plumbing for V1:

  - make_report_id()      -> "CND-YYYYMMDD-xxxxxx"
  - confidence_from(meta) -> "High" | "Medium" | "Low" (from data depth)
  - ledger_entry(...)     -> Public Honesty Ledger record (data structure only;
                             the public calibration page comes later)
  - log_report(...)       -> append an admin row (report_id, date, market, best
                             firm, pass odds, killer rule, payment status)
  - capture_email(...)    -> store an email against a report_id

IMPORTANT PERSISTENCE CAVEAT
----------------------------
These writers append to local files. On Streamlit Community Cloud the filesystem
is EPHEMERAL — it resets on every reboot/redeploy. So this is a correct *skeleton*
but it is NOT a durable store. Before you rely on captured emails or the ledger
for anything real, point _append() at a real backend (a database, a Google
Sheet via API, or a form service). Until then, treat captured data as
best-effort and possibly transient. Do not promise users their data is retained.
"""

from __future__ import annotations
import json
import os
import time
import uuid
from datetime import date

_BASE = os.path.dirname(os.path.abspath(__file__))
ADMIN_LOG = os.environ.get("ADMIN_LOG", os.path.join(_BASE, "admin_log.csv"))
EMAILS_LOG = os.environ.get("EMAILS_LOG", os.path.join(_BASE, "emails.csv"))
LEDGER_LOG = os.environ.get("LEDGER_LOG", os.path.join(_BASE, "ledger.jsonl"))


def make_report_id() -> str:
    return f"CND-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"


def confidence_from(meta: dict) -> str:
    """Honest confidence from how much history we had to work with."""
    n = (meta or {}).get("n_days", 0)
    if n >= 30:
        return "High"
    if n >= 15:
        return "Medium"
    return "Low"


def ledger_entry(report_id, ruleset_version, simulation_date,
                 main_killer_rule, pass_odds, confidence) -> dict:
    """
    A single Public Honesty Ledger record. `outcome` stays None until the user
    later reports what actually happened (did they pass, which rule hit them).
    Aggregating these powers the future 'Candor Calibration' page.
    """
    return {
        "report_id": report_id,
        "ruleset_version": ruleset_version,
        "simulation_date": simulation_date,
        "main_killer_rule": main_killer_rule,
        "pass_odds": round(float(pass_odds), 4),
        "confidence": confidence,
        "outcome": None,           # {"passed": bool, "failed_rule": str} when submitted
        "created_ts": int(time.time()),
    }


def _append_line(path: str, line: str) -> None:
    try:
        new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return new
    except Exception:
        return False  # never break the product over logging


def log_report(report_id, market_type, best_firm, pass_odds,
               killer_rule, payment_status) -> None:
    header = "report_id,date,market_type,best_firm,pass_odds,killer_rule,payment_status"
    if not os.path.exists(ADMIN_LOG):
        _append_line(ADMIN_LOG, header)
    row = ",".join([
        report_id, str(date.today()), str(market_type).replace(",", " "),
        str(best_firm).replace(",", " "), f"{pass_odds:.4f}",
        str(killer_rule).replace(",", " "), str(payment_status),
    ])
    _append_line(ADMIN_LOG, row)


def capture_email(email: str, report_id: str, context: str = "report") -> bool:
    """Store an email against a report. Returns True if it looks valid & stored."""
    email = (email or "").strip()
    if "@" not in email or "." not in email.split("@")[-1] or len(email) < 5:
        return False
    if not os.path.exists(EMAILS_LOG):
        _append_line(EMAILS_LOG, "ts,email,report_id,context")
    _append_line(EMAILS_LOG, f"{int(time.time())},{email},{report_id},{context}")
    return True


def write_ledger(entry: dict) -> None:
    _append_line(LEDGER_LOG, json.dumps(entry))
