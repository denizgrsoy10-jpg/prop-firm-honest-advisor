"""
sequence_risk.py
================
Path-dependency / sequence-risk layer.

WHY THIS EXISTS (the heavy lifting a trader can't do by hand):
A naive Monte Carlo that samples days *independently* (rng.choice) destroys the
one thing that actually kills challenge accounts: the ORDER of results. Real
traders don't have independent days — losses cluster (tilt, revenge trading),
wins cluster (momentum). Trailing-drawdown and daily-limit rules are violently
sensitive to that clustering. The same set of daily P/L, reshuffled, can pass
70% of the time or 30% of the time depending only on sequence.

This module adds three things the trader cannot compute in a spreadsheet:

  1) AUTOCORRELATION MEASUREMENT — does this trader's history actually streak?
     We measure lag-1 autocorrelation of daily P/L and the observed run-length
     distribution, so we know whether independence is a safe assumption (it
     usually isn't).

  2) BLOCK BOOTSTRAP — instead of resampling single days, we resample
     *contiguous blocks* of days (Künsch 1989, the standard method for
     dependent time series). This preserves the streakiness, so simulated
     attempts contain realistic losing/winning runs instead of artificially
     smooth ones.

  3) SEQUENCE-RISK SCORE — we take the trader's OWN days (no resampling) and
     permute their order many times, measuring how often a bad ordering breaks
     the account. This isolates pure path-dependency: same days, same totals,
     only the sequence changes. A high score means "your results are survivable
     on average but a bad run-of-the-cards wipes you" — a risk no single-number
     win-rate can show.

All three are PRESENTATION/DIAGNOSTIC layers on top of the existing rule
checker (rules_engine.evaluate_phase). They do not change a firm's rules; they
change how realistically we sample sequences and they expose the path risk.
"""

from __future__ import annotations
import math
import random
from dataclasses import dataclass

from rules_engine import evaluate_phase, BREACH_LABELS


# ---------------------------------------------------------------------------
# 1) Autocorrelation + run-length diagnostics
# ---------------------------------------------------------------------------
def lag1_autocorrelation(daily_pnls: list[float]) -> float | None:
    """Lag-1 autocorrelation of the daily P/L series.

    >0  : good/bad days tend to follow themselves (streaky) -> independence
          assumption understates tail risk.
    ~0  : days look independent.
    <0  : mean-reverting (a loss tends to be followed by a gain).
    Returns None if the series is too short or has zero variance.
    """
    n = len(daily_pnls)
    if n < 3:
        return None
    mean = sum(daily_pnls) / n
    var = sum((x - mean) ** 2 for x in daily_pnls)
    if var == 0:
        return None
    cov = sum((daily_pnls[i] - mean) * (daily_pnls[i + 1] - mean)
              for i in range(n - 1))
    return cov / var


def _sign_runs(daily_pnls: list[float]) -> list[int]:
    """Lengths of consecutive same-sign runs (a 'streak profile').
    Zeros are treated as non-winning (grouped with losses) for run purposes."""
    runs = []
    cur_sign = None
    cur_len = 0
    for p in daily_pnls:
        s = 1 if p > 0 else -1
        if s == cur_sign:
            cur_len += 1
        else:
            if cur_len:
                runs.append(cur_len if cur_sign == 1 else -cur_len)
            cur_sign = s
            cur_len = 1
    if cur_len:
        runs.append(cur_len if cur_sign == 1 else -cur_len)
    return runs


def streak_profile(daily_pnls: list[float]) -> dict:
    """Observed longest winning / losing streaks and a streakiness label."""
    runs = _sign_runs(daily_pnls)
    longest_win = max([r for r in runs if r > 0], default=0)
    longest_loss = -min([r for r in runs if r < 0], default=0)
    ac = lag1_autocorrelation(daily_pnls)
    if ac is None:
        label = "Not enough data to judge streakiness."
        streaky = None
    elif ac > 0.15:
        label = ("Your results streak: good and bad days cluster. Independent "
                 "models understate how often a losing run stacks up.")
        streaky = True
    elif ac < -0.15:
        label = ("Your results mean-revert: a bad day tends to be followed by a "
                 "better one. That softens run-of-the-cards risk.")
        streaky = False
    else:
        label = "Your day-to-day results look roughly independent."
        streaky = None
    return {
        "lag1_autocorr": ac,
        "longest_win_streak": longest_win,
        "longest_loss_streak": longest_loss,
        "streaky": streaky,
        "label": label,
    }


# ---------------------------------------------------------------------------
# 2) Block bootstrap (preserves streaks the trader actually has)
# ---------------------------------------------------------------------------
def _optimal_block_len(n: int, autocorr: float | None) -> int:
    """Pick a block length. More autocorrelation -> longer blocks so streaks
    survive resampling. Falls back to ~sqrt(n) (a common rule of thumb)."""
    base = max(2, round(math.sqrt(n)))
    if autocorr is None:
        return base
    if autocorr > 0.30:
        return min(n, base + 3)
    if autocorr > 0.15:
        return min(n, base + 1)
    return base


def block_bootstrap_path(daily_pnls: list[float], horizon: int,
                         block_len: int, rng: random.Random) -> list[float]:
    """Build a synthetic path by stitching contiguous blocks (circular).

    Unlike single-day resampling, this keeps real runs intact: if the trader
    has a habit of 4-day losing streaks, those streaks show up in simulation
    instead of being averaged away.
    """
    n = len(daily_pnls)
    path: list[float] = []
    while len(path) < horizon:
        start = rng.randrange(n)
        for j in range(block_len):
            path.append(daily_pnls[(start + j) % n])
            if len(path) >= horizon:
                break
    return path


# ---------------------------------------------------------------------------
# 3) Sequence-risk score (same days, only the order changes)
# ---------------------------------------------------------------------------
@dataclass
class SequenceRisk:
    pass_rate_shuffled: float        # how often a random ordering of the SAME days passes
    worst_quartile_pass: float       # pass rate of the worst 25% of orderings
    order_sensitivity: float         # spread between lucky and unlucky orderings (0..1)
    dominant_breach_key: str
    dominant_breach_label: str
    label: str


def sequence_risk(daily_pnls: list[float], firm: dict, phase_index: int = 0,
                  iters: int = 1500, seed: int = 13) -> SequenceRisk | None:
    """Permute the trader's OWN days (no resampling) and measure path risk.

    This isolates pure sequence effect: every shuffle has identical days and an
    identical final total — only the order differs. If many orderings break the
    account, the trader is exposed to run-of-the-cards risk that a single
    win-rate or average-drawdown number completely hides.
    """
    days = list(daily_pnls)
    if len(days) < 4:
        return None
    rng = random.Random(seed)

    passes = 0
    breaches: dict[str, int] = {}
    # We bucket each ordering's outcome to estimate the worst-quartile behaviour.
    # outcome = 1 if pass else 0; we also track which rule broke it.
    outcomes: list[int] = []
    for _ in range(iters):
        rng.shuffle(days)
        res = evaluate_phase(days, firm, phase_index)
        if res.passed:
            passes += 1
            outcomes.append(1)
        else:
            outcomes.append(0)
            if res.breach_reason:
                breaches[res.breach_reason] = breaches.get(res.breach_reason, 0) + 1

    pass_rate = passes / iters

    # Worst-quartile pass rate: sort outcomes, take bottom 25% (all the 0s first).
    # Equivalent to: in the unluckiest quarter of orderings, how often do we pass?
    outcomes_sorted = sorted(outcomes)               # 0s first, then 1s
    q = max(1, iters // 4)
    worst_quartile_pass = sum(outcomes_sorted[:q]) / q

    # Order sensitivity: gap between best-case and worst-case quartiles.
    best_quartile_pass = sum(outcomes_sorted[-q:]) / q
    order_sensitivity = best_quartile_pass - worst_quartile_pass

    if breaches:
        dom_key = max(breaches, key=breaches.get)
    else:
        dom_key = "target_not_reached"
    dom_label = BREACH_LABELS.get(dom_key, dom_key)

    # Human label
    if pass_rate >= 0.6 and order_sensitivity >= 0.3:
        label = ("Fragile to sequence: on average your days clear this ruleset, "
                 "but an unlucky ordering of the very same results breaks it far "
                 "more often. Your risk is the run, not the average.")
    elif order_sensitivity >= 0.3:
        label = ("High sequence sensitivity: the order of your results matters "
                 "as much as the results themselves here.")
    elif pass_rate < 0.3:
        label = ("Order barely matters — most sequences of your days miss the "
                 "target regardless. The issue is the edge, not the ordering.")
    else:
        label = ("Low sequence sensitivity: your outcome is fairly stable no "
                 "matter what order your days arrive in.")

    return SequenceRisk(
        pass_rate_shuffled=pass_rate,
        worst_quartile_pass=worst_quartile_pass,
        order_sensitivity=order_sensitivity,
        dominant_breach_key=dom_key,
        dominant_breach_label=dom_label,
        label=label,
    )
