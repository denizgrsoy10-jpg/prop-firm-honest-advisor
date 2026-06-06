"""
signal_scan.py — Signal Scanner V0 (red-flag checklist only).

This is NOT trading advice and gives NO opinion on direction. It only inspects a
pasted "signal" for missing risk hygiene (stop, size, invalidation, R/R, time
horizon) and hype language, and returns a disclosure score. Pure function so it's
trivially testable; storage happens in tracking.log_signal_scan.
"""
from __future__ import annotations
import hashlib
import re

_GUARANTEE = re.compile(r"\b(guarantee|guaranteed|risk[\s-]?free|sure thing|100%|can'?t lose|easy money)\b", re.I)
_HAS_SL = re.compile(r"\b(sl|stop[\s-]?loss|stop)\b", re.I)
_HAS_SIZE = re.compile(r"\b(lot|lots|risk \d|position size|% risk|units|contracts)\b", re.I)
_HAS_INVALID = re.compile(r"\b(invalidat|if it breaks|below|above|structure)\b", re.I)
_HAS_RR = re.compile(r"\b(r[:/]r|risk[\s/]reward|rr\b|reward)\b", re.I)
_HAS_TIME = re.compile(r"\b(today|tomorrow|this week|h1|h4|daily|intraday|swing|by \w+day|hold)\b", re.I)


def scan_signal(text: str) -> dict:
    t = (text or "").strip()
    flags = []
    if not _HAS_SL.search(t):
        flags.append("No stop loss / invalidation price")
    if not _HAS_SIZE.search(t):
        flags.append("No position sizing or risk amount")
    if not _HAS_RR.search(t):
        flags.append("No risk / reward stated")
    if not _HAS_INVALID.search(t):
        flags.append("No clear level that would prove it wrong")
    if not _HAS_TIME.search(t):
        flags.append("No time horizon")
    if _GUARANTEE.search(t):
        flags.append("Uses guarantee / 'risk-free' language (major red flag)")

    n = len(flags)
    score = min(100, n * 17 + (15 if _GUARANTEE.search(t) else 0))
    if score >= 67 or _GUARANTEE.search(t):
        level = "High Risk"
    elif score >= 34:
        level = "Suspicious"
    else:
        level = "Clean-ish"

    return {
        "risk_level": level,
        "risk_score": score,
        "red_flags": flags,
        "text_hash": hashlib.sha256(t.encode()).hexdigest()[:16] if t else "",
        "label": ("Signal quality / risk-disclosure scan only. Not trading advice, "
                  "not an opinion on direction. A 'clean' checklist does not make a "
                  "signal profitable."),
    }
