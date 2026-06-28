"""
consistency_risk.py — Layer 8: Consistency Rule Risk

Many prop firms enforce a CONSISTENCY rule: your single best trading day's
profit may not exceed X% of your total net profit. Break it and you're
eliminated — even though you hit the profit target. Apex applies ~30% on
funded accounts; Topstep applies 50% on both the Combine and funded; FundingPips
and others vary. Most traders have never heard of it and don't see it coming.

This is a real, separate elimination path: "I made the money and still failed."
This module simulates how often the trader's own daily pattern would trip a
consistency cap at the moment they reach the profit target.

Pure-Python (no scipy/numpy). Diagnostic only, not advice.

Masking note (showroom name, mechanism hidden):
  - "Consistency Cap Test"  (the best-day-vs-total-profit elimination check)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict
import random


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------
@dataclass
class ConsistencyRisk:
    """Result of a consistency-cap analysis for one firm."""
    firm: str
    cap_pct: float                 # the consistency threshold (e.g. 30 or 50)
    cap_source: str                # "published" | "funded-stage" | "estimated"
    target_profit: float

    # Core outcomes (over simulated challenge paths that reach the target)
    pass_target_rate: float = 0.0          # P(reach profit target at all)
    consistency_kill_rate: float = 0.0     # of those, P(fail consistency)
    clean_pass_rate: float = 0.0           # P(reach target AND clear consistency)

    # Behavioural read on the trader
    best_day_share: float = 0.0            # best single day / total net profit
    headroom: float = 0.0                  # how far under/over the cap they sit

    # Narrative
    headline: str = ""
    detail: str = ""
    label: str = ""
    available: bool = True
    applies: bool = True                   # False when no firm in scope caps


# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------
def _simulate_consistency(
    daily_pnls: List[float],
    cap_pct: float,
    target_profit: float,
    window: int,
    trials: int,
    seed: int,
) -> tuple:
    """Return (pass_target_rate, kill_rate, clean_pass_rate).

    Each trial resamples `window` days (preserving the trader's own daily
    distribution). A path 'reaches target' if its cumulative net profit clears
    `target_profit`. Among those, it 'fails consistency' if the single best day
    exceeds cap_pct% of the cumulative net profit.
    """
    rng = random.Random(seed)
    reached = 0
    killed = 0
    clean = 0
    for _ in range(trials):
        path = [rng.choice(daily_pnls) for _ in range(window)]
        total = sum(path)
        if total >= target_profit and total > 0:
            reached += 1
            best = max(path)
            if best > total * cap_pct / 100.0:
                killed += 1
            else:
                clean += 1
    pass_rate = reached / trials
    kill_rate = (killed / reached) if reached else 0.0
    clean_rate = clean / trials
    return pass_rate, kill_rate, clean_rate


def _best_day_share(daily_pnls: List[float]) -> float:
    """Best single day as a fraction of total NET profit (sum of all days).

    Uses net profit (not gross wins) because that's what the consistency rule
    measures against. Guarded for non-positive totals.
    """
    total = sum(daily_pnls)
    if total <= 0:
        return 0.0
    best = max(daily_pnls) if daily_pnls else 0.0
    if best <= 0:
        return 0.0
    return best / total


# ---------------------------------------------------------------------------
# Firm cap resolution
# ---------------------------------------------------------------------------
def _resolve_cap(firm: dict) -> tuple:
    """Return (cap_pct, source) for a firm, or (None, None) if no cap applies.

    Priority:
      1. Structured consistency_rule_pct (applies during evaluation).
      2. Funded-stage cap hinted in the source note (e.g. Apex 30% on funded).
      3. None — firm has no consistency cap in scope.
    """
    structured = firm.get("consistency_rule_pct")
    if structured:
        return float(structured), "published"

    # Funded-stage caps live in the source note for some firms.
    note = (firm.get("source_note") or "").lower()
    if "consistency" in note:
        # Look for a "NN%" near the word consistency / funded.
        import re
        # Prefer a percentage that co-occurs with 'funded' or 'consistency'
        for m in re.finditer(r"(\d{1,2})\s*%", note):
            start = max(0, m.start() - 40)
            ctx = note[start:m.end() + 10]
            if "consist" in ctx or "funded" in ctx:
                return float(m.group(1)), "funded-stage"

    return None, None


# ---------------------------------------------------------------------------
# Public entry point — single firm
# ---------------------------------------------------------------------------
def consistency_report(
    firm: dict,
    daily_pnls: List[float],
    *,
    trials: int = 3000,
    seed: int = 42,
) -> ConsistencyRisk:
    """Build a ConsistencyRisk result for one firm from the trader's daily P/L."""
    name = firm.get("firm_name", "This firm")
    account = float(firm.get("account_size", 50000) or 50000)
    phases = firm.get("phases") or []
    target_pct = float(phases[0].get("target_pct", 8)) if phases else 8.0
    target_profit = account * target_pct / 100.0

    cap_pct, source = _resolve_cap(firm)

    # No consistency cap in scope for this firm
    if cap_pct is None:
        return ConsistencyRisk(
            firm=name, cap_pct=0.0, cap_source="none",
            target_profit=target_profit, applies=False, available=True,
            headline=f"{name} has no consistency cap in the rules we track.",
            label="No consistency rule applies to this ruleset in our verified set.",
        )

    if not daily_pnls or len(daily_pnls) < 5:
        return ConsistencyRisk(
            firm=name, cap_pct=cap_pct, cap_source=source or "published",
            target_profit=target_profit, available=False,
            label="Not enough trading history to simulate the consistency cap.",
        )

    window = len(daily_pnls)
    pass_rate, kill_rate, clean_rate = _simulate_consistency(
        daily_pnls, cap_pct, target_profit, window, trials, seed,
    )

    best_share = _best_day_share(daily_pnls)
    headroom = (cap_pct / 100.0) - best_share  # positive = under the cap

    # --- narrative ----------------------------------------------------------
    src_word = {
        "published": "published",
        "funded-stage": "funded-stage",
        "estimated": "estimated",
    }.get(source, "published")

    headline = (
        f"{name} enforces a {cap_pct:.0f}% consistency cap ({src_word}): your "
        f"single best day can't exceed {cap_pct:.0f}% of total profit. In this "
        f"simulation, {kill_rate*100:.0f}% of paths that hit the target would "
        f"still be eliminated by it."
    )

    if best_share <= 0:
        share_line = ("Your history has no net profit concentration to measure "
                      "yet, so this is a structural read rather than a personal one.")
    else:
        share_line = (
            f"Your single best day is about {best_share*100:.0f}% of your total "
            f"net profit, versus the {cap_pct:.0f}% cap — "
            + ("comfortably under it."
               if headroom > 0.08 else
               "close to the line." if headroom >= 0 else
               "already over the line on your full history.")
        )

    if kill_rate >= 0.4:
        risk_line = ("This is a major elimination path for your pattern: hitting "
                     "the target is not enough if one day carries too much of the "
                     "profit.")
    elif kill_rate >= 0.15:
        risk_line = ("This is a real secondary risk: some of your target-hitting "
                     "runs concentrate profit into one day and trip the cap.")
    else:
        risk_line = ("This cap is a minor risk for your current pattern — your "
                     "profit is spread across enough days.")

    detail = f"{share_line} {risk_line}"

    label = (
        f"Consistency-cap simulation from your uploaded history "
        f"({src_word} cap). The consistency rule is a separate elimination path "
        f"from the drawdown and target rules; this is a diagnostic of exposure, "
        f"not a recommendation or a guarantee."
    )

    return ConsistencyRisk(
        firm=name, cap_pct=cap_pct, cap_source=source or "published",
        target_profit=target_profit,
        pass_target_rate=pass_rate, consistency_kill_rate=kill_rate,
        clean_pass_rate=clean_rate, best_day_share=best_share,
        headroom=headroom, headline=headline, detail=detail, label=label,
        available=True, applies=True,
    )


# ---------------------------------------------------------------------------
# Convenience: pick the most relevant capped firm for the trader
# ---------------------------------------------------------------------------
def best_consistency_target(results, firms_by_name: dict, daily_pnls: List[float]):
    """From simulate_all results (sorted by pass odds), find the highest-fit
    firm that actually enforces a consistency cap and analyse it. If none of
    the top firms cap, fall back to the single best-fit firm so the report can
    still state that no cap applies.
    """
    if not results:
        return None

    # Walk results best-first; prefer the first firm that has a cap.
    fallback_firm = None
    for r in results:
        firm = getattr(r, "firm", None)
        if not isinstance(firm, dict):
            if isinstance(firm, str):
                firm = firms_by_name.get(firm)
            if not isinstance(firm, dict):
                continue
        if fallback_firm is None:
            fallback_firm = firm
        cap_pct, _src = _resolve_cap(firm)
        if cap_pct is not None:
            return consistency_report(firm, daily_pnls)

    # No capped firm among results — report "no cap applies" on the best fit.
    if fallback_firm is not None:
        return consistency_report(fallback_firm, daily_pnls)
    return None
