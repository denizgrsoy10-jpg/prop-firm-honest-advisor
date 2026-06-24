"""
kelly.py
========
Fifth layer of heavy lifting: Kelly-criterion edge & sizing analysis,
adapted for prop-firm challenges — and scrupulously honest about its limits.

WHY THIS EXISTS:
Every trader silently asks "how big should I size?" Almost all get it wrong:
  - OVERBETTING past the growth-optimal fraction is the most common blow-up
    cause. Beyond the Kelly peak, MORE risk gives LESS expected growth AND more
    ruin -- a brutal fact no win-rate shows.
  - UNDERBETTING so small you can't reach a target inside the window burns fees.

The Kelly criterion gives the growth-optimal fraction from the trader's OWN
edge. We compute it honestly from the P/L series, translate it into the
fractional Kelly a drawdown-capped challenge actually calls for, and grade the
edge that drives it.

HONESTY BOUNDARY (the important part):
A trade-history CSV does NOT contain the trader's account size or per-trade
risk %, so we CANNOT truthfully say "you are 2x over Kelly". Inventing that
multiple would be exactly the false precision Candor refuses to sell. So we
report what the data CAN support -- the edge, the Kelly fraction, the prudent
fractional range, and a clear note that mapping it to YOUR live size requires
your account size, which the upload doesn't include.

The math here (edge estimation, payoff ratio, discrete + continuous Kelly,
fractional-Kelly reasoning under a drawdown floor) is real work a trader cannot
do in a spreadsheet. It is diagnostic only.
"""

from __future__ import annotations
import statistics
from dataclasses import dataclass


@dataclass
class KellyResult:
    has_edge: bool
    win_rate: float
    payoff_ratio: float
    kelly_fraction: float
    kelly_continuous: float
    edge_grade: str
    recommended_fraction_label: str
    headline: str
    detail: str
    sizing_note: str
    disclaimer: str = ("Kelly analysis derived from your uploaded history. "
                       "Growth-optimal sizing is volatile; most professionals risk "
                       "a fraction of full Kelly. Diagnostic only -- not advice.")


def _mean(xs):
    return statistics.mean(xs) if xs else 0.0


def kelly_analysis(daily_pnls):
    """Compute Kelly edge & sizing diagnostics from a daily P/L series."""
    if len(daily_pnls) < 6:
        return None

    wins = [p for p in daily_pnls if p > 0]
    losses = [abs(p) for p in daily_pnls if p < 0]

    if not losses:
        return KellyResult(
            has_edge=True, win_rate=1.0, payoff_ratio=float("inf"),
            kelly_fraction=0.0, kelly_continuous=0.0, edge_grade="undetermined",
            recommended_fraction_label="-",
            headline="No losing days in this sample - Kelly can't be estimated yet.",
            detail=("Every day here is a win, so there's no downside to size "
                    "against. That's usually too few or too clean a sample; add "
                    "more days (including losers) for a real sizing read."),
            sizing_note="")

    if not wins:
        return KellyResult(
            has_edge=False, win_rate=0.0, payoff_ratio=0.0,
            kelly_fraction=0.0, kelly_continuous=0.0, edge_grade="negative",
            recommended_fraction_label="0% - no positive edge to size",
            headline="No winning days in this sample - no positive edge.",
            detail=("With no wins, the growth-optimal bet is not to bet. The issue "
                    "is the edge, not the size."),
            sizing_note="")

    win_rate = len(wins) / len(daily_pnls)
    avg_win = _mean(wins)
    avg_loss = _mean(losses)
    b = avg_win / avg_loss if avg_loss > 0 else float("inf")

    p = win_rate
    q = 1.0 - p
    kelly_f = p - q / b if b > 0 else 0.0

    mean_ret = statistics.mean(daily_pnls)
    var_ret = statistics.pvariance(daily_pnls)
    kelly_c = (mean_ret / var_ret) if var_ret > 0 else 0.0

    has_edge = kelly_f > 0 and mean_ret > 0

    if not has_edge:
        edge_grade = "negative"
        rec_label = "0% - no positive expectancy in this sample"
        headline = ("Your sample shows no positive expectancy - Kelly's "
                    "growth-optimal size is essentially zero.")
        detail = ("Kelly only sizes a real edge. Here the average day doesn't "
                  "clear its own variance, so the math points to not sizing up "
                  "until the edge improves. The fix is the edge, not the size.")
        sizing_note = ("Until expectancy turns positive, larger size just reaches "
                       "ruin faster - this is the one case where sizing down can't "
                       "save a losing process.")
    else:
        half_k = kelly_f * 0.5
        quarter_k = kelly_f * 0.25
        rec_label = (f"Full Kelly ~ {kelly_f*100:.0f}% of bankroll per bet "
                     f"\u00b7 half-Kelly ~ {half_k*100:.0f}% \u00b7 quarter-Kelly ~ "
                     f"{quarter_k*100:.0f}%")

        if kelly_f >= 0.20 and b >= 1.0:
            edge_grade = "strong"
            headline = (f"Solid edge in this sample: full Kelly ~ "
                        f"{kelly_f*100:.0f}% of bankroll per bet.")
        elif kelly_f >= 0.05:
            edge_grade = "thin"
            headline = (f"Thin but positive edge: full Kelly ~ "
                        f"{kelly_f*100:.0f}% of bankroll per bet - small enough "
                        f"that estimation error matters.")
        else:
            edge_grade = "marginal"
            headline = (f"Marginal edge: full Kelly ~ {kelly_f*100:.0f}% - barely "
                        f"above zero, so treat it as fragile.")

        detail = ("Full Kelly maximises long-run growth but is famously volatile - "
                  "deep drawdowns are normal even when sized 'correctly'. Under a "
                  "challenge's hard drawdown floor that volatility is dangerous, so "
                  "the prudent range is half- to quarter-Kelly: you give up a little "
                  "growth for a large cut in ruin risk and a smoother equity path "
                  "that survives more orderings of the same days.")

        sizing_note = ("Mapping this to YOUR live size needs your account size and "
                       "per-trade risk %, which the upload doesn't include - so we "
                       "show the growth-optimal fraction, not a verdict on your "
                       "current size. If you risk well under half-Kelly per trade, "
                       "oversizing isn't your risk; if you're near or above full "
                       "Kelly, the challenge floor makes that the danger.")

    return KellyResult(
        has_edge=has_edge,
        win_rate=win_rate,
        payoff_ratio=b,
        kelly_fraction=kelly_f,
        kelly_continuous=kelly_c,
        edge_grade=edge_grade,
        recommended_fraction_label=rec_label,
        headline=headline,
        detail=detail,
        sizing_note=sizing_note,
    )
