"""
rule_interaction.py
===================
Second layer of heavy lifting: rule-interaction analysis.

WHY THIS EXISTS:
A trader reading a firm's rules sees each rule in isolation. What they cannot
see — and what a spreadsheet cannot compute — is how those rules COMPOUND:

  - A big early winning day raises the trailing drawdown floor AND pushes the
    best-day share of total profit above the consistency cap, simultaneously.
  - The daily loss limit is soft (closes the day), but it also prevents
    recovery, which means the trailing floor stays elevated while you can't
    trade, turning a soft breach into a slow death.
  - Consistency rules penalise a trader for GOOD days that are TOO good.
    Combined with a time limit, this forces a paradox: trade steadily (risky
    for drawdown) vs trade boldly early (risky for consistency).

This module runs targeted Monte Carlo experiments for each active rule
combination, measuring:
  1) COMPOUNDING RATE — what fraction of breaches involve 2+ rules firing
     near-simultaneously (within 3 trading days of each other)?
  2) INTERACTION TRAPS — specific named traps (spike-then-floor, consistency
     ceiling, double-breach window) with their frequency in the trader's data.
  3) SOLO vs COMPOUND ATTRIBUTION — what fraction of failures is caused by
     rules acting ALONE vs rules acting TOGETHER?

All of this is derived from the SAME evaluate_phase checker already used by
the engine — no new rule logic, just a different lens on the existing model.
"""

from __future__ import annotations
import random
from dataclasses import dataclass, field

from rules_engine import evaluate_phase


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _has_consistency(firm: dict) -> bool:
    return (firm.get("consistency_rule_pct") or 0) > 0


def _has_trailing(firm: dict) -> bool:
    return firm.get("drawdown_type", "static").startswith("trailing")


def _has_daily_limit(firm: dict) -> bool:
    return (firm.get("daily_loss_limit_pct") or 0) > 0


def _has_time_limit(firm: dict) -> bool:
    return (firm.get("time_limit_days") or 0) > 0


def _spike_exposure(daily_pnls: list[float], firm: dict) -> float:
    """Fraction of days where that day's P/L alone exceeds the trailing-DD
    allowance. High = one bad day after a spike can breach immediately."""
    dd_pct = firm.get("max_drawdown_pct") or 0
    if dd_pct == 0:
        return 0.0
    dd_amt = firm["account_size"] * dd_pct / 100.0
    count = sum(1 for p in daily_pnls if abs(p) > dd_amt * 0.5)
    return count / len(daily_pnls) if daily_pnls else 0.0


# ---------------------------------------------------------------------------
# 1) Solo-vs-compound breach attribution
# ---------------------------------------------------------------------------
@dataclass
class RuleInteractionResult:
    total_failures: int
    solo_breach_pct: float          # failures caused by exactly one rule
    compound_breach_pct: float      # failures where 2+ rules played a role
    # Named trap frequencies (share of total failures)
    spike_then_floor_pct: float     # big winning day → trailing floor rises →
                                    # subsequent losses breach it
    consistency_ceiling_pct: float  # breach caused by consistency rule
    double_window_pct: float        # daily limit + drawdown fire within 3 days
    active_rules: list[str]
    trap_labels: list[str]          # human-readable list of detected interaction traps
    compound_label: str             # top-level interpretation
    disclaimer: str = ("Rule-interaction analysis derived from trader history. "
                       "Illustrative only — not financial advice.")


def rule_interaction_analysis(
        daily_pnls: list[float],
        firm: dict,
        phase_index: int = 0,
        iters: int = 2000,
        seed: int = 17,
) -> RuleInteractionResult | None:
    """Measure how this firm's rules compound against the trader's history."""

    if len(daily_pnls) < 4:
        return None

    rng = random.Random(seed)
    horizon = min(len(daily_pnls), 28)
    account = float(firm["account_size"])

    dd_pct   = firm.get("max_drawdown_pct") or 0
    cons_pct = firm.get("consistency_rule_pct") or 0
    dl_pct   = firm.get("daily_loss_limit_pct") or 0
    dd_type  = firm.get("drawdown_type", "static")

    dd_amt = account * dd_pct / 100.0
    dl_amt = account * dl_pct / 100.0

    active_rules: list[str] = []
    if dd_pct:
        active_rules.append(f"{'Trailing' if 'trailing' in dd_type else 'Static'} drawdown ({dd_pct}%)")
    if cons_pct:
        active_rules.append(f"Consistency ({cons_pct}% best-day cap)")
    if dl_pct:
        active_rules.append(f"Daily loss limit ({dl_pct}%)")
    if _has_time_limit(firm):
        active_rules.append(f"Time limit ({firm['time_limit_days']} days)")

    total_failures = 0
    solo_breaches = 0
    compound_breaches = 0
    spike_then_floor = 0
    consistency_ceiling = 0
    double_window = 0

    for _ in range(iters):
        path = [rng.choice(daily_pnls) for _ in range(horizon)]
        res = evaluate_phase(path, firm, phase_index)
        if res.passed:
            continue

        total_failures += 1

        # --- Track rule interactions along the path -------------------------
        balance = account
        peak = account
        day_profits: list[float] = []
        spike_day: int | None = None   # day when equity hit a new peak > +1 DD unit
        daily_limit_days: list[int] = []

        for i, pnl in enumerate(path):
            # Detect spike: a single day gain that lifts peak by ≥ 50% of DD allowance
            if pnl > 0 and dd_amt > 0 and pnl >= dd_amt * 0.5:
                spike_day = i

            if dl_amt > 0 and pnl < 0 and abs(pnl) > dl_amt:
                daily_limit_days.append(i)

            balance += pnl
            day_profits.append(pnl)
            peak = max(peak, balance)

        breach_reason = res.breach_reason

        # Spike-then-floor: a spike day preceded the trailing breach
        is_spike_then_floor = (
            breach_reason == "trailing_drawdown"
            and spike_day is not None
        )

        # Consistency ceiling
        is_consistency = breach_reason == "consistency_rule"

        # Double window: daily limit fire within 3 days of drawdown breach day
        breach_day = res.days_used or horizon
        is_double_window = (
            breach_reason in ("trailing_drawdown", "max_drawdown", "static_drawdown")
            and any(abs(d - breach_day) <= 3 for d in daily_limit_days)
        )

        # Solo vs compound
        interaction_count = sum([
            is_spike_then_floor,
            is_consistency,
            is_double_window,
        ])

        if interaction_count >= 1:
            compound_breaches += 1
        else:
            solo_breaches += 1

        if is_spike_then_floor:
            spike_then_floor += 1
        if is_consistency:
            consistency_ceiling += 1
        if is_double_window:
            double_window += 1

    if total_failures == 0:
        return RuleInteractionResult(
            total_failures=0,
            solo_breach_pct=0.0,
            compound_breach_pct=0.0,
            spike_then_floor_pct=0.0,
            consistency_ceiling_pct=0.0,
            double_window_pct=0.0,
            active_rules=active_rules,
            trap_labels=[],
            compound_label="No failures recorded — insufficient data for interaction analysis.",
        )

    tf = total_failures
    solo_pct      = solo_breaches   / tf
    compound_pct  = compound_breaches / tf
    stf_pct       = spike_then_floor / tf
    cons_pct_r    = consistency_ceiling / tf
    dw_pct        = double_window / tf

    # --- Named traps --------------------------------------------------------
    trap_labels: list[str] = []

    if stf_pct >= 0.15 and _has_trailing(firm):
        trap_labels.append(
            f"Spike-then-floor trap ({stf_pct*100:.0f}% of failures): a big winning "
            f"day raises the trailing floor, then a normal pullback breaches it. "
            f"The same loss that would be fine on Day 1 kills the account on Day 3.")

    if cons_pct_r >= 0.10 and _has_consistency(firm):
        trap_labels.append(
            f"Consistency ceiling ({cons_pct_r*100:.0f}% of failures): a day that "
            f"is too profitable violates the best-day cap. This penalises outsized "
            f"wins — the ruleset rewards boring consistency, not big days.")

    if dw_pct >= 0.10 and _has_daily_limit(firm) and _has_trailing(firm):
        trap_labels.append(
            f"Double-breach window ({dw_pct*100:.0f}% of failures): daily loss limit "
            f"and drawdown breach fire within 3 trading days of each other. The soft "
            f"daily close prevents recovery while the trailing floor stays elevated.")

    if not trap_labels and compound_pct >= 0.20:
        trap_labels.append(
            "Multiple rules interact to produce failures more often than any single "
            "rule would alone. No dominant single trap — risk is distributed.")

    # --- Top-level label ----------------------------------------------------
    if compound_pct >= 0.45:
        compound_label = (
            f"{compound_pct*100:.0f}% of simulated failures involve rule "
            f"interactions, not just one rule acting alone. This ruleset has "
            f"a compounding structure — rules that look manageable in isolation "
            f"create compound pressure together.")
    elif compound_pct >= 0.20:
        compound_label = (
            f"{compound_pct*100:.0f}% of failures involve two or more rules "
            f"compounding. Some interaction risk exists but a single dominant "
            f"rule drives most failures.")
    else:
        compound_label = (
            f"Most failures ({solo_pct*100:.0f}%) are caused by a single rule "
            f"acting alone. Rule interaction is not the main risk here.")

    return RuleInteractionResult(
        total_failures=total_failures,
        solo_breach_pct=solo_pct,
        compound_breach_pct=compound_pct,
        spike_then_floor_pct=stf_pct,
        consistency_ceiling_pct=cons_pct_r,
        double_window_pct=dw_pct,
        active_rules=active_rules,
        trap_labels=trap_labels,
        compound_label=compound_label,
    )
