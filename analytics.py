"""
analytics.py
------------
Minimal, dependency-free event logging. Writes one JSON object per line to
analytics.jsonl (configurable). Swap _sink() for a real analytics provider
later without touching call sites.

No PII is logged — only event names and non-identifying properties.
"""

from __future__ import annotations
import json
import os
import time

ALLOWED_EVENTS = {
    "upload_started",
    "parse_success",
    "parse_failed",
    "preview_viewed",
    "unlock_clicked",
    "payment_success",
    "full_report_viewed",
    "pdf_downloaded",
    "rerun_clicked",
}

LOG_PATH = os.environ.get("ANALYTICS_LOG", os.path.join(os.path.dirname(__file__),
                                                         "analytics.jsonl"))


def log_event(name: str, props: dict | None = None) -> None:
    if name not in ALLOWED_EVENTS:
        # fail soft: don't crash the app over an analytics typo
        return
    record = {"ts": int(time.time()), "event": name, "props": props or {}}
    _sink(record)


def _sink(record: dict) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass  # analytics must never break the product
