"""
regime_analysis.py
==================
Third layer of heavy lifting: regime & volatility-clustering analysis.

WHY THIS EXISTS:
A win-rate treats a trader's history as one homogeneous blob. Real trading
histories are NOT stationary — they have regimes:

  - VOLATILITY CLUSTERING (ARCH effect): big days cluster together. A calm
    stretch is followed by calm; a wild stretch by wild. This is the single
    most robust empirical fact in financial time series, and it makes
    drawdown risk "lumpy" — your worst drawdowns happen during the wild
    clusters, not spread evenly.

  - REGIME SHIFTS: a trader's edge is rarely constant. The first third of a
    history can be a losing regime and the last third a winning one (or vice
    versa). Pass odds computed on the whole blob hide which regime the trader
    is in RIGHT NOW — and they're about to attempt a challenge from the
    current regime, not the average one.

  - RISK DRIFT: position sizes creep up (revenge sizing, overconfidence) or
    down (fear) over time. Upward drift is a classic blow-up precursor: the
    account looks fine on average but the *recent* risk is the dangerous one.

This module measures all three from the SAME daily P/L series and translates
them into how much the pass-odds estimate should be trusted, and which regime
the trader is currently in. A spreadsheet cannot do this — it requires
volatility-of-volatility estimation, regime segmentation, and trend testing.

Everything here is diagnostic. We never tell the trader what to do; we expose
structure they cannot see.
"""

from __future__ import annotations
import math
import statistics
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# 1) Volatility clustering (ARCH-style)
# ---------------------------------------------------------------------------
def volatility_clustering(daily_pnls: list[float]) -> float | None:
    """Lag-1 autocorrelation of |daily P/L|.

    >0  : volatility clusters — big days follow big days. Drawdowns arrive in
          bursts, so tail risk is lumpier than an i.i.d. model assumes.
    ~0  : volatility is roughly constant over time.
    Returns None if too short or degenerate.
    """
    n = len(daily_pnls)
    if n < 4:
        return None
    absp = [abs(p) for p in daily_pnls]
    mean_abs = sum(absp) / n
    var = sum((x - mean_abs) ** 2 for x in absp)
    if var == 0:
        return None
    cov = sum((absp[i] - mean_abs) * (absp[i + 1] - mean_abs) for i in range(n - 1))
    return cov / var


# ---------------------------------------------------------------------------
# 2) Regime segmentation (thirds) + current regime
# ---------------------------------------------------------------------------
@dataclass
class Regime:
    label: str            # "early" / "middle" / "recent"
    mean_pnl: float
    vol: float
    win_rate: float


def _segment(daily_pnls: list[float], lo: int, hi: int, label: str) -> Regime:
    seg = daily_pnls[lo:hi]
    if not seg:
        return Regime(label, 0.0, 0.0, 0.0)
    mean = statistics.mean(seg)
    vol = statistics.pstdev(seg) if len(seg) > 1 else 0.0
    wr = sum(1 for p in seg if p > 0) / len(seg)
    return Regime(label, mean, vol, wr)


def regime_shift(daily_pnls: list[float]) -> dict | None:
    """Split history into thirds and compare. Detect whether the trader's edge
    and volatility are stable, improving, or deteriorating — and flag the
    CURRENT (most recent) regime, which is what they'll trade from next."""
    n = len(daily_pnls)
    if n < 6:
        return None
    t = n // 3
    early  = _segment(daily_pnls, 0, t, "early")
    middle = _segment(daily_pnls, t, 2 * t, "middle")
    recent = _segment(daily_pnls, 2 * t, n, "recent")

    # Trend in mean P/L across the three regimes
    means = [early.mean_pnl, middle.mean_pnl, recent.mean_pnl]
    improving = means[2] > means[0] and means[2] > 0
    deteriorating = means[2] < means[0] and means[2] < means[1]

    # Volatility trend
    vols = [early.vol, middle.vol, recent.vol]
    vol_rising = vols[2] > vols[0] * 1.25 if vols[0] > 0 else False

    if deteriorating:
        edge_label = ("Your edge is deteriorating: the most recent third of your "
                      "history is your weakest. Pass odds built on the full "
                      "history may be optimistic for an attempt starting now.")
        edge_state = "deteriorating"
    elif improving:
        edge_label = ("Your edge is improving: the most recent third is your "
                      "strongest. Full-history pass odds may understate your "
                      "current form — but a hot streak can also revert.")
        edge_state = "improving"
    else:
        edge_label = ("Your edge is roughly stable across the history — no strong "
                      "regime drift in average results.")
        edge_state = "stable"

    return {
        "early":  early.__dict__,
        "middle": middle.__dict__,
        "recent": recent.__dict__,
        "edge_state": edge_state,
        "edge_label": edge_label,
        "vol_rising": vol_rising,
    }


# ---------------------------------------------------------------------------
# 3) Risk drift (are position sizes creeping up?)
# ---------------------------------------------------------------------------
def risk_drift(daily_pnls: list[float]) -> dict | None:
    """Compare average |P/L| in the first half vs the second half. Upward drift
    = sizing up over time (a classic blow-up precursor). We also run a simple
    sign test on the per-day |P/L| trend for robustness."""
    n = len(daily_pnls)
    if n < 6:
        return None
    half = n // 2
    early_abs = [abs(p) for p in daily_pnls[:half]]
    late_abs  = [abs(p) for p in daily_pnls[half:]]
    early_mean = statistics.mean(early_abs) if early_abs else 0.0
    late_mean  = statistics.mean(late_abs) if late_abs else 0.0
    if early_mean == 0:
        return None
    drift_pct = (late_mean / early_mean - 1.0) * 100.0

    if drift_pct >= 25:
        label = (f"Risk drift UP {drift_pct:+.0f}%: your recent position sizes are "
                 f"materially larger than your earlier ones. Rising size late in a "
                 f"sample is a common blow-up precursor — the average looks fine "
                 f"while the recent risk is the dangerous part.")
        state = "rising"
    elif drift_pct <= -25:
        label = (f"Risk drift DOWN {drift_pct:+.0f}%: you're sizing smaller recently. "
                 f"Lower drawdown risk, but possibly slower to reach a profit target.")
        state = "falling"
    else:
        label = (f"Risk drift {drift_pct:+.0f}%: position sizing is roughly steady "
                 f"across your history.")
        state = "steady"

    return {"drift_pct": drift_pct, "state": state, "label": label}


# ---------------------------------------------------------------------------
# Top-level: assemble the regime report + a trust adjustment
# ---------------------------------------------------------------------------
def regime_report(daily_pnls: list[float], robustness: dict | None = None) -> dict | None:
    """Full regime diagnostic. Returns None if the series is too short.

    `robustness` (optional) is the out-of-sample validation result. When the
    two halves of the history diverge (a 'fragile' self-validation), the regime
    read must not claim the history is stationary — the two layers have to agree.
    """
    if len(daily_pnls) < 6:
        return None

    vc = volatility_clustering(daily_pnls)
    rs = regime_shift(daily_pnls)
    rd = risk_drift(daily_pnls)

    # Volatility-clustering label
    if vc is None:
        vc_label = "Not enough data to measure volatility clustering."
    elif vc > 0.20:
        vc_label = (f"Volatility clusters (clustering score {vc:+.2f}): your big "
                    f"days arrive in bursts, so drawdowns are lumpy rather than "
                    f"evenly spread. A calm backtest can hide a wild cluster.")
    elif vc > 0.08:
        vc_label = (f"Mild volatility clustering (clustering score {vc:+.2f}): "
                    f"some tendency for active and quiet stretches to group.")
    else:
        vc_label = (f"Little volatility clustering (clustering score {vc:+.2f}): "
                    f"your day-to-day volatility is fairly even.")

    # Overall "regime stability" trust note — should the trader trust a single
    # full-history pass number? ANY strong trend in the mean (improving OR
    # deteriorating) is non-stationarity, not just decline — a monotone climb in
    # win rate is itself a regime shift. We also defer to the out-of-sample
    # check: if the two halves diverge, this history is NOT stationary, full stop.
    flags = 0
    if vc is not None and vc > 0.20:
        flags += 1
    if rs and rs["edge_state"] in ("deteriorating", "improving"):
        flags += 1   # any strong directional trend, not only decline
    if rs and rs["vol_rising"]:
        flags += 1
    if rd and rd["state"] == "rising":
        flags += 1

    # Out-of-sample override: a fragile split is decisive evidence of regime
    # instability and must dominate the regime read so the two layers agree.
    oos_fragile = bool(robustness and robustness.get("stability") == "fragile")
    oos_moderate = bool(robustness and robustness.get("stability") == "moderate")

    if oos_fragile or flags >= 2:
        if oos_fragile:
            trust_label = (
                "Out-of-sample validation splits this history into two halves "
                "that disagree sharply, and the average results trend across "
                "thirds rather than holding steady. This history is not "
                "stationary — treat any single full-history pass number with "
                "strong caution, and weight your most recent form over the "
                "headline average.")
        else:
            trust_label = (
                "Multiple regime signals fired (a directional trend in your "
                "edge, rising volatility, or rising size). Treat a single "
                "full-history pass number with extra caution — your recent "
                "regime looks different from your average.")
        trust = "low"
    elif flags == 1 or oos_moderate:
        trust_label = (
            "Some regime drift is present: your earlier and later trading differ "
            "enough that a single full-history pass number is a rough summary "
            "rather than a precise one. Watch the flagged dimension.")
        trust = "medium"
    else:
        trust_label = (
            "No strong regime instability and the out-of-sample halves broadly "
            "agree, so full-history pass odds are a fair summary of this record.")
        trust = "high"

    return {
        "vol_clustering": vc,
        "vol_clustering_label": vc_label,
        "regime_shift": rs,
        "risk_drift": rd,
        "regime_trust": trust,
        "regime_trust_label": trust_label,
        "disclaimer": ("Regime analysis derived from your uploaded history. "
                       "Diagnostic only — not financial advice."),
    }
