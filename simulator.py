"""
simulator.py
------------
Monte Carlo over a trader's daily P/L. We bootstrap (sample daily results with
replacement) to build many synthetic challenge attempts and measure how often
they pass each firm's rules, and which rule most often ends the failures.

This is a deliberately simple, transparent V1 engine — not the final model.
Its assumptions are reported alongside every result; we never imply precision
we don't have.
"""

from __future__ import annotations
import random
from dataclasses import dataclass, field

from rules_engine import evaluate_phase, BREACH_LABELS

DEFAULT_ITERS = 2000
MAX_HORIZON = 30  # trading days simulated per phase


@dataclass
class FirmResult:
    firm: dict
    pass_prob: float                      # 0..1, full challenge (all phases chained)
    phase1_prob: float
    killer_rule_key: str
    killer_rule_label: str
    breach_breakdown: dict                # reason_key -> share of failures
    median_final_balance: float
    sample_curve: list[float] = field(default_factory=list)
    note: str = ""


def _simulate_phase_prob(daily_pnls, firm, phase_index, iters, horizon, rng):
    """Return (pass_prob, breach_counter, sample_curve, median_final)."""
    if not daily_pnls:
        return 0.0, {}, [], firm["account_size"]
    passes = 0
    breaches: dict[str, int] = {}
    finals = []
    sample_curve = []
    for k in range(iters):
        path = [rng.choice(daily_pnls) for _ in range(horizon)]
        res = evaluate_phase(path, firm, phase_index)
        finals.append(res.final_balance)
        if res.passed:
            passes += 1
        elif res.breach_reason:
            breaches[res.breach_reason] = breaches.get(res.breach_reason, 0) + 1
        if k == 0:
            sample_curve = res.equity_curve
    finals.sort()
    median = finals[len(finals) // 2] if finals else firm["account_size"]
    return passes / iters, breaches, sample_curve, median


def simulate_firm(daily_pnls: list[float], firm: dict,
                  iters: int = DEFAULT_ITERS, seed: int | None = None) -> FirmResult:
    rng = random.Random(seed)
    horizon = min(max(len(daily_pnls), firm.get("min_trading_days", 0) or 1), MAX_HORIZON)

    # Phase 1
    p1, breaches, curve, median = _simulate_phase_prob(
        daily_pnls, firm, 0, iters, horizon, rng)

    # Chain remaining phases (approx: independent, same daily distribution).
    overall = p1
    for pi in range(1, len(firm.get("phases", [{}]))):
        pp, _, _, _ = _simulate_phase_prob(daily_pnls, firm, pi, iters, horizon, rng)
        overall *= pp

    total_breaches = sum(breaches.values()) or 1
    breakdown = {k: v / total_breaches for k, v in breaches.items()}
    if breaches:
        killer_key = max(breaches, key=breaches.get)
    else:
        killer_key = "target_not_reached"
    killer_label = BREACH_LABELS.get(killer_key, killer_key)

    note = ""
    if firm.get("drawdown_type", "").startswith("trailing"):
        note = "Trailing drawdown estimated from end-of-day balances (no intraday data)."
    if firm.get("instrument_class") == "futures":
        note = (note + " Futures $ thresholds approximated as % of account.").strip()

    return FirmResult(
        firm=firm,
        pass_prob=overall,
        phase1_prob=p1,
        killer_rule_key=killer_key,
        killer_rule_label=killer_label,
        breach_breakdown=breakdown,
        median_final_balance=median,
        sample_curve=curve,
        note=note,
    )


def simulate_all(daily_pnls: list[float], firms: list[dict],
                 iters: int = DEFAULT_ITERS, seed: int | None = 42) -> list[FirmResult]:
    results = [simulate_firm(daily_pnls, f, iters=iters, seed=seed) for f in firms]
    results.sort(key=lambda r: r.pass_prob, reverse=True)
    return results


def verdict_for(prob: float) -> str:
    """One-word honest verdict from a pass probability."""
    if prob >= 0.55:
        return "go"
    if prob >= 0.30:
        return "wait"
    return "skip"
