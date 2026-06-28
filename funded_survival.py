"""
funded_survival.py — Layer 7: Funded Account Survival

The challenge is the easy part. Most traders pass an evaluation and then lose
the funded account, because the funded stage is a DIFFERENT game:
  - usually no profit target (just survive + produce profit)
  - the drawdown floor keeps trailing
  - new rules can switch on (e.g. funded-only consistency caps)
  - payouts require a minimum profit threshold + minimum trading days
  - profit is split (trader keeps ~80-90%)

This module simulates what happens AFTER the pass: how long the trader's own
historical daily pattern survives the funded drawdown floor, and whether they
reach a first payout before busting.

Pure-Python (no scipy/numpy needed). Diagnostic only, not advice.

Masking note (showroom names, recipe hidden):
  - "Funded Survival Horizon"  (the survival-curve simulation)
  - "First Payout Path"        (the payout-vs-bust race)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import random
import statistics


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------
@dataclass
class FundedSurvival:
    """Result of a funded-account survival analysis for one firm."""
    firm: str
    account_size: float
    dd_pct: float
    dd_is_trailing: bool

    # Survival curve: probability of still holding the account after N days
    horizons: List[int] = field(default_factory=list)        # e.g. [30, 60, 90]
    survival_rates: List[float] = field(default_factory=list)  # parallel to horizons
    median_days_survived: float = 0.0

    # First-payout race
    payout_threshold: float = 0.0
    profit_split: float = 0.0
    min_days: int = 0
    reach_payout_rate: float = 0.0       # P(reach first payout)
    blow_before_payout_rate: float = 0.0  # P(bust before first payout)
    avg_first_payout: float = 0.0         # trader's cut, averaged over successes

    # Narrative
    headline: str = ""
    detail: str = ""
    label: str = ""
    available: bool = True


# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------
def _simulate_survival(
    daily_pnls: List[float],
    account: float,
    dd_amount: float,
    dd_is_trailing: bool,
    days: int,
    trials: int,
    seed: int,
) -> tuple:
    """Return (survival_rate, median_days_survived) over `days` horizon.

    The funded account has no profit target — the trader simply trades their
    historical daily distribution and we check whether the (trailing) drawdown
    floor is ever touched within the horizon.
    """
    rng = random.Random(seed)
    survived = 0
    days_list = []
    for _ in range(trials):
        balance = account
        peak = account
        floor = account - dd_amount
        day_out = days
        for d in range(days):
            balance += rng.choice(daily_pnls)
            if dd_is_trailing and balance > peak:
                peak = balance
                floor = peak - dd_amount   # trailing floor ratchets up
            if balance <= floor:
                day_out = d + 1
                break
        if day_out >= days:
            survived += 1
        days_list.append(day_out)
    return survived / trials, statistics.median(days_list)


def _simulate_first_payout(
    daily_pnls: List[float],
    account: float,
    dd_amount: float,
    dd_is_trailing: bool,
    payout_threshold: float,
    min_days: int,
    profit_split: float,
    max_days: int,
    trials: int,
    seed: int,
) -> tuple:
    """Return (reach_rate, blow_rate, avg_payout_to_trader).

    Races two outcomes: reaching a first payout (profit >= threshold after at
    least `min_days`) vs. busting the floor first.
    """
    rng = random.Random(seed)
    reached = 0
    blown = 0
    payouts = []
    for _ in range(trials):
        balance = account
        peak = account
        floor = account - dd_amount
        days_traded = 0
        outcome = "timeout"
        for _d in range(max_days):
            balance += rng.choice(daily_pnls)
            days_traded += 1
            if dd_is_trailing and balance > peak:
                peak = balance
                floor = peak - dd_amount
            if balance <= floor:
                outcome = "blown"
                break
            profit = balance - account
            if profit >= payout_threshold and days_traded >= min_days:
                outcome = "payout"
                payouts.append(profit * profit_split)
                break
        if outcome == "payout":
            reached += 1
        elif outcome == "blown":
            blown += 1
    avg_payout = statistics.mean(payouts) if payouts else 0.0
    return reached / trials, blown / trials, avg_payout


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def funded_survival_report(
    firm: dict,
    daily_pnls: List[float],
    *,
    horizons: tuple = (30, 60, 90),
    trials: int = 2000,
    seed: int = 42,
) -> FundedSurvival:
    """Build a FundedSurvival result for one firm from the trader's daily P/L.

    `firm` is a loaded firm-rules dict; we read account_size, max_drawdown_pct,
    and (if present) trailing-drawdown / consistency / payout hints. Where a
    firm doesn't publish a funded payout threshold we fall back to a documented
    typical value and mark it as an estimate in the label.
    """
    name = firm.get("firm_name", "This firm")
    account = float(firm.get("account_size", 50000) or 50000)
    dd_pct = float(firm.get("max_drawdown_pct", 5) or 5)
    dd_amount = account * dd_pct / 100.0

    # Is the funded drawdown trailing? Default to the eval's trailing flag.
    dd_is_trailing = bool(firm.get("trailing_drawdown", True))

    # Need enough signal to simulate
    if not daily_pnls or len(daily_pnls) < 5:
        return FundedSurvival(
            firm=name, account_size=account, dd_pct=dd_pct,
            dd_is_trailing=dd_is_trailing, available=False,
            label="Not enough trading history to simulate funded survival.",
        )

    # --- survival curve -----------------------------------------------------
    surv_rates = []
    median_days = 0.0
    for h in horizons:
        rate, med = _simulate_survival(
            daily_pnls, account, dd_amount, dd_is_trailing,
            days=h, trials=trials, seed=seed,
        )
        surv_rates.append(rate)
        if h == horizons[len(horizons) // 2]:
            median_days = med

    # --- first payout race --------------------------------------------------
    # Typical funded payout threshold: published where available, else a
    # documented common value (~4% of account) marked estimated.
    payout_threshold = float(firm.get("funded_payout_threshold", 0) or 0)
    threshold_estimated = False
    if payout_threshold <= 0:
        payout_threshold = round(account * 0.04, -2)  # ~4% of account
        threshold_estimated = True

    profit_split = float(firm.get("funded_profit_split", 0) or 0)
    split_estimated = False
    if profit_split <= 0:
        profit_split = 0.90  # common 90/10
        split_estimated = True

    min_days = int(firm.get("funded_min_payout_days", 0) or 0)
    if min_days <= 0:
        min_days = 10  # common minimum

    reach, blow, avg_payout = _simulate_first_payout(
        daily_pnls, account, dd_amount, dd_is_trailing,
        payout_threshold=payout_threshold, min_days=min_days,
        profit_split=profit_split, max_days=max(horizons),
        trials=trials, seed=seed + 1,
    )

    # --- narrative ----------------------------------------------------------
    h_lo, h_mid, h_hi = horizons[0], horizons[len(horizons) // 2], horizons[-1]
    r_lo = surv_rates[0]
    r_hi = surv_rates[-1]

    headline = (
        f"Passing is the easy part. In this simulation, holding the funded "
        f"account drops from {r_lo*100:.0f}% at {h_lo} days to "
        f"{r_hi*100:.0f}% at {h_hi} days."
    )

    # Decay framing
    if r_hi < 0.4:
        decay = ("The funded floor keeps trailing your equity, so a long run of "
                 "ordinary losses erodes the account over time even without a "
                 "profit target to chase.")
    elif r_hi < 0.65:
        decay = ("Survival thins out the longer you trade: the trailing floor "
                 "gives back less room than the evaluation window suggested.")
    else:
        decay = ("This pattern holds the funded floor relatively well over the "
                 "simulated horizon, though longer horizons always add risk.")

    payout_line = (
        f"First-payout path: {reach*100:.0f}% reach a first payout "
        f"(~${avg_payout:,.0f} to you at {profit_split*100:.0f}% split), while "
        f"{blow*100:.0f}% bust the floor before getting there."
    )

    detail = f"{decay} {payout_line}"

    notes = []
    if threshold_estimated:
        notes.append("payout threshold estimated (~4% of account)")
    if split_estimated:
        notes.append("profit split assumed 90/10")
    note_str = ("; ".join(notes)) if notes else "from published funded rules where available"

    label = (
        f"Funded-stage simulation from your uploaded history — {note_str}. "
        f"The funded account is a separate stage with its own rules; this is a "
        f"diagnostic of expectation, not a recommendation or a guarantee."
    )

    return FundedSurvival(
        firm=name, account_size=account, dd_pct=dd_pct,
        dd_is_trailing=dd_is_trailing,
        horizons=list(horizons), survival_rates=surv_rates,
        median_days_survived=median_days,
        payout_threshold=payout_threshold, profit_split=profit_split,
        min_days=min_days, reach_payout_rate=reach,
        blow_before_payout_rate=blow, avg_first_payout=avg_payout,
        headline=headline, detail=detail, label=label, available=True,
    )


# ---------------------------------------------------------------------------
# Convenience: pick the firm the trader is most likely to actually fund
# ---------------------------------------------------------------------------
def best_funded_target(results, firms_by_name: dict, daily_pnls: List[float]):
    """Given simulate_all results (sorted by pass odds), build a funded
    survival analysis for the single best-fit firm — the one the trader is
    most likely to actually reach the funded stage with.

    `results[0].firm` is already the loaded firm dict, so we use it directly;
    `firms_by_name` is accepted for backwards-compatibility but not required.
    """
    if not results:
        return None
    top = results[0]
    firm = getattr(top, "firm", None)
    if isinstance(firm, dict):
        return funded_survival_report(firm, daily_pnls)
    # Fallback: resolve by name if firm came through as a string
    if isinstance(firm, str) and firms_by_name:
        resolved = firms_by_name.get(firm)
        if resolved is not None:
            return funded_survival_report(resolved, daily_pnls)
    return None
