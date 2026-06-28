"""
robustness.py — Layer 9: Out-of-Sample Validation

Every other layer tells you what the model concludes. This one asks the harder
question: how much should you trust that conclusion at all?

A pass-odds number from a short history can be a real edge — or the fingerprint
of a hot streak that's about to revert. The only honest way to tell them apart
is to make the model prove itself out-of-sample: learn from the first half of
the trader's history, then test that prediction on the second half it never saw.
If the two halves agree, the edge is probably real and the headline odds are
trustworthy. If they diverge wildly, the single number is hiding a regime split,
and the trader should gather more data before betting on it.

No prop tool does this, because it means the product grading its own homework in
public. Candor's whole brand is honesty, so this belongs here.

Pure-Python (no scipy/numpy). Diagnostic only, not advice.

Masking note (showroom name, mechanism hidden):
  - "Self-Validation Split"  (the train/test out-of-sample check)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import random
import statistics


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------
@dataclass
class Robustness:
    """Out-of-sample validation result for the best-fit firm."""
    firm: str
    n_days: int
    train_days: int
    test_days: int

    train_pass: float = 0.0       # pass odds learned on first half
    test_pass: float = 0.0        # pass odds observed on second half
    full_pass: float = 0.0        # pass odds on the whole history
    gap: float = 0.0              # |train - test|

    stability: str = ""           # "stable" | "moderate" | "fragile"
    trust_score: int = 0          # 0-100, higher = more trustworthy headline

    headline: str = ""
    detail: str = ""
    label: str = ""
    available: bool = True


# ---------------------------------------------------------------------------
# Core: a lightweight pass simulation shared by both halves
# ---------------------------------------------------------------------------
def _pass_rate(
    pnls: List[float],
    account: float,
    target: float,
    dd_amount: float,
    dd_is_trailing: bool,
    window: int,
    trials: int,
    seed: int,
) -> Optional[float]:
    """Probability of clearing `target` before touching the drawdown floor,
    resampling `window` days from `pnls` (preserves the half's own distribution).
    Returns None if the half is too small to simulate.
    """
    if not pnls or len(pnls) < 3:
        return None
    rng = random.Random(seed)
    passed = 0
    for _ in range(trials):
        bal = account
        peak = account
        floor = account - dd_amount
        ok = False
        for _d in range(window):
            bal += rng.choice(pnls)
            if dd_is_trailing and bal > peak:
                peak = bal
                floor = peak - dd_amount
            if bal <= floor:
                break
            if bal - account >= target:
                ok = True
                break
        if ok:
            passed += 1
    return passed / trials


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def robustness_report(
    firm: dict,
    daily_pnls: List[float],
    *,
    window: int = 20,
    trials: int = 2500,
    seed: int = 17,
) -> Robustness:
    """Build an out-of-sample validation result for one firm.

    Splits the trader's daily history in half (chronologically), learns pass
    odds on the first half, tests on the second, and reports how well the two
    agree. A small gap means the headline odds are trustworthy; a large gap
    means the single number is masking a regime split.
    """
    name = firm.get("firm_name", "This firm")
    n = len(daily_pnls)

    # Need enough days to split meaningfully (at least ~6 per half + signal)
    if n < 12:
        return Robustness(
            firm=name, n_days=n, train_days=0, test_days=0, available=False,
            label=("Not enough trading history to validate out-of-sample yet — "
                   "this check needs a longer record to split into train/test."),
        )

    account = float(firm.get("account_size", 50000) or 50000)
    phases = firm.get("phases") or []
    target_pct = float(phases[0].get("target_pct", 8)) if phases else 8.0
    target = account * target_pct / 100.0
    dd_amount = account * float(firm.get("max_drawdown_pct", 5) or 5) / 100.0
    dd_is_trailing = bool(firm.get("trailing_drawdown", True))

    mid = n // 2
    first_half = daily_pnls[:mid]
    second_half = daily_pnls[mid:]

    train_pass = _pass_rate(first_half, account, target, dd_amount,
                            dd_is_trailing, window, trials, seed)
    test_pass = _pass_rate(second_half, account, target, dd_amount,
                           dd_is_trailing, window, trials, seed + 1)
    full_pass = _pass_rate(daily_pnls, account, target, dd_amount,
                           dd_is_trailing, window, trials, seed + 2)

    if train_pass is None or test_pass is None:
        return Robustness(
            firm=name, n_days=n, train_days=len(first_half),
            test_days=len(second_half), available=False,
            label=("One half of your history was too thin to validate "
                   "out-of-sample. Add more trades to enable this check."),
        )

    gap = abs(train_pass - test_pass)

    # Stability bands + trust score
    if gap < 0.10:
        stability = "stable"
        trust_score = max(60, int(100 - gap * 400))   # ~60-100
    elif gap < 0.25:
        stability = "moderate"
        trust_score = int(60 - (gap - 0.10) * 200)     # ~30-60
    else:
        stability = "fragile"
        trust_score = max(5, int(30 - (gap - 0.25) * 80))  # ~5-30

    # --- narrative ----------------------------------------------------------
    headline = (
        f"Out-of-sample check: trained on your first {len(first_half)} days "
        f"({train_pass*100:.0f}% odds), tested on your last {len(second_half)} "
        f"({test_pass*100:.0f}% odds). The two halves "
        + ("agree closely." if stability == "stable"
           else "differ somewhat." if stability == "moderate"
           else "diverge sharply.")
    )

    if stability == "stable":
        detail = (
            f"Your pattern reproduces across both halves, so the headline "
            f"{full_pass*100:.0f}% is a fair summary rather than an artifact of "
            f"one lucky stretch. This is the strongest case the data can make "
            f"for treating the odds as real."
        )
    elif stability == "moderate":
        detail = (
            f"There is some drift between your earlier and later trading, so the "
            f"headline {full_pass*100:.0f}% is reasonable but not rock-solid. "
            f"Treat it as a central estimate with real uncertainty on either side."
        )
    else:
        detail = (
            f"Your two halves tell very different stories, so the single "
            f"{full_pass*100:.0f}% figure is averaging a weak stretch and a "
            f"strong one. That pattern is the fingerprint of a hot-or-cold run "
            f"rather than a stable edge — the honest move is more data before "
            f"trusting any single number."
        )

    label = (
        "Out-of-sample validation splits your own history into train and test "
        "halves — the model checking its own prediction on data it didn't learn "
        "from. A diagnostic of how much to trust the headline odds, not a "
        "recommendation or a guarantee."
    )

    return Robustness(
        firm=name, n_days=n, train_days=len(first_half),
        test_days=len(second_half), train_pass=train_pass, test_pass=test_pass,
        full_pass=full_pass, gap=gap, stability=stability,
        trust_score=trust_score, headline=headline, detail=detail, label=label,
        available=True,
    )


# ---------------------------------------------------------------------------
# Convenience: validate on the best-fit firm
# ---------------------------------------------------------------------------
def best_robustness(results, daily_pnls: List[float]):
    """Run out-of-sample validation on the single best-fit firm from
    simulate_all results (sorted by pass odds).
    """
    if not results:
        return None
    top = results[0]
    firm = getattr(top, "firm", None)
    if isinstance(firm, dict):
        return robustness_report(firm, daily_pnls)
    return None
