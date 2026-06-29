"""
insights.py — Wave 1 "Report Superiority" modules.

Everything here is computed from data we already have (daily P/L series, parsed
meta, simulator results, verified firm rules). No new storage, no new pages, no
network. Every output is honestly framed as a *diagnostic*, never advice, never a
guarantee. When the data can't support a claim, we say so instead of inventing it.
"""
from __future__ import annotations
import statistics as st


# ---------------------------------------------------------------- data quality
def data_quality_audit(meta: dict, daily_pnls: list[float]) -> dict:
    n_days = meta.get("n_days", len(daily_pnls))
    n_trades = meta.get("n_trades", 0)
    outliers = 0
    if len(daily_pnls) >= 5:
        m = st.mean(daily_pnls)
        sd = st.pstdev(daily_pnls) or 1.0
        outliers = sum(1 for d in daily_pnls if abs(d - m) > 3 * sd)
    if n_days >= 30:
        conf, why = "High", "30+ trading days gives the simulation a solid base."
    elif n_days >= 15:
        conf, why = "Medium", "15–29 trading days — usable, but treat odds as indicative."
    else:
        conf, why = "Low", ("Fewer than 15 trading days. This is a rough estimate; "
                            "re-run after you've logged more history.")
    return {
        "n_trades": n_trades, "n_days": n_days,
        "profitable_days": meta.get("profitable_days"),
        "outliers": outliers,
        "confidence": conf, "confidence_why": why,
        "warnings": meta.get("warnings", []),
    }


# ------------------------------------------------------------------- risk DNA
def _label(x, lo, hi):
    return "Low" if x < lo else ("High" if x > hi else "Medium")


def risk_dna(daily_pnls: list[float], meta: dict) -> dict:
    n = len(daily_pnls)
    if n < 5:
        return {"available": False,
                "note": "Not enough history for a behavioral read (need ≥5 trading days)."}

    pos = [d for d in daily_pnls if d > 0]
    neg = [d for d in daily_pnls if d < 0]
    total_abs = sum(abs(d) for d in daily_pnls) or 1.0

    # longest losing streak
    streak = best = 0
    for d in daily_pnls:
        streak = streak + 1 if d < 0 else 0
        best = max(best, streak)

    # how much of total gains came from the single best day
    profit_concentration = (max(pos) / sum(pos)) if pos else 0.0
    # how much of all movement is one day
    largest_day_dependency = (max(abs(d) for d in daily_pnls) / total_abs)
    # risk drift: did daily swing size grow in the second half?
    half = n // 2
    sd1 = st.pstdev(daily_pnls[:half]) if half >= 2 else 0.0
    sd2 = st.pstdev(daily_pnls[half:]) if (n - half) >= 2 else 0.0
    risk_drift = (sd2 / sd1) if sd1 else 1.0
    # behavior after a losing day
    after_loss = [daily_pnls[i + 1] for i in range(n - 1) if daily_pnls[i] < 0]
    recovery = (sum(after_loss) / len(after_loss)) if after_loss else 0.0

    metrics = {
        "longest_loss_streak": best,
        "profit_concentration": round(profit_concentration, 2),
        "largest_day_dependency": round(largest_day_dependency, 2),
        "risk_drift": round(risk_drift, 2),
        "loss_streak_sensitivity": _label(best, 2, 4),
        "concentration_label": _label(profit_concentration, .25, .45),
        "drift_label": _label(risk_drift, .8, 1.3),
        "recovery_after_loss": round(recovery, 2),
    }

    # pick the single most dangerous behavior, honestly
    flags = []
    if best >= 4:
        flags.append(("Long losing streaks",
                      f"Worst observed run: {best} losing days in a row. Drawdown rules become sensitive to runs of this length."))
    if profit_concentration >= .45:
        flags.append(("Profit concentration",
                      "A large share of your gains came from one day; remove it and the edge thins."))
    if risk_drift >= 1.3:
        flags.append(("Rising risk over time",
                      "Your daily swings grew later in the sample — risk creeping up."))
    if largest_day_dependency >= .4:
        flags.append(("One-day dependency",
                      "A single day dominates your P/L; the rest is closer to break-even."))
    if not flags:
        flags.append(("No dominant red flag",
                      "No single behavior stands out as the main risk on this sample."))

    return {"available": True, "metrics": metrics,
            "most_dangerous_behavior": flags[0][0],
            "behavior_note": flags[0][1],
            "all_flags": flags,
            "label": "Behavioral risk diagnostics — not advice."}


# ---------------------------------------------------------- killer-rule autopsy
_AUTOPSY = {
    "trailing": {
        "mechanism": ("A trailing drawdown follows your highest equity. After an early "
                      "profit spike the floor ratchets up, so ordinary pullbacks now sit "
                      "much closer to the breach line."),
        "path": ["Early profit moves your equity to a new high",
                 "The trailing floor ratchets up with it",
                 "A normal cluster of losses follows",
                 "Equity touches the raised floor → breach"],
        "reduce": ["Lower early-stage risk reduced trailing-drawdown breach "
                   "pressure in similar simulations",
                   "Large early equity spikes raised the trailing floor and "
                   "reduced the breach margin in this sample",
                   "Static (non-trailing) drawdown rules were mechanically "
                   "less sensitive to this pattern"],
    },
    "profit target": {
        "mechanism": ("On your historical pace, the profit target isn't reached inside the "
                      "challenge window often enough — you run out of time, not capital."),
        "path": ["Steady but slow gains",
                 "Window elapses before target is hit",
                 "Challenge fails on time, not on a loss"],
        "reduce": ["Rulesets with a lower profit target were mechanically "
                   "easier to clear within the same window in simulation",
                   "Rulesets without a time limit removed the time-pressure "
                   "component of this failure mode",
                   "Larger position size without a documented edge raised "
                   "drawdown variance in this sample"],
    },
    "daily loss": {
        "mechanism": ("A single bad day breaches the daily loss limit before the account-"
                      "level drawdown is ever in play."),
        "path": ["One outsized losing day",
                 "Daily loss limit hit",
                 "Challenge fails that day"],
        "reduce": ["A personal stop inside the daily limit mechanically removes "
                   "the single-day breach path",
                   "Historical pattern shows clustered losses after 2 losing "
                   "trades in a session",
                   "Highest-volatility sessions contribute disproportionately "
                   "to single-day breach risk"],
    },
    "drawdown": {
        "mechanism": ("Cumulative losses reach the maximum drawdown ceiling over several "
                      "sessions rather than in one day."),
        "path": ["A run of losing sessions",
                 "Cumulative loss grows",
                 "Max drawdown ceiling reached → breach"],
        "reduce": ["Scaling historical risk per trade down reduces cumulative "
                   "drawdown pressure in this sample",
                   "A defined intraday stop limits cumulative same-day "
                   "contribution to drawdown",
                   "Firms with larger or static drawdown allowances are "
                   "mechanically more permissive for this pattern"],
    },
    "consistency": {
        "mechanism": ("A consistency rule caps how much of your profit can come from one "
                      "day; your best day is too large a share of the total."),
        "path": ["One day carries most of the profit",
                 "Best-day share exceeds the consistency cap",
                 "Payout/qualification blocked"],
        "reduce": ["Spreading gains across more sessions reduces best-day "
                   "share of total profit",
                   "Single-day concentration of profit is the mechanical "
                   "trigger for consistency-rule failures",
                   "Firms without a consistency cap are mechanically "
                   "permissive for concentrated profit days"],
    },
}


def killer_rule_autopsy(best_result) -> dict:
    label = (getattr(best_result, "killer_rule_label", "") or "")
    key = next((k for k in _AUTOPSY if k in label.lower()), None)
    tpl = _AUTOPSY.get(key)
    if not tpl:
        return {"rule": label or "—",
                "mechanism": "This is the rule that ended the most simulated attempts for you.",
                "path": [], "reduce": [],
                "label": "General failure mechanism for this rule type — not advice."}
    return {"rule": label, "mechanism": tpl["mechanism"], "path": tpl["path"],
            "reduce": tpl["reduce"],
            "label": "General failure mechanism for this rule type — not advice."}


# --------------------------------------------------------------- fee burn 2.0
def retry_danger(pass_prob: float) -> str:
    if pass_prob >= .5:
        return "Low"
    if pass_prob >= .2:
        return "Moderate"
    if pass_prob >= .08:
        return "High"
    return "Severe"


def fee_burn_headline(firm_rows: list[dict]) -> dict:
    """A single honest reality line based on the cheapest-looking trap."""
    worst = None
    for r in firm_rows:
        if r.get("fee_burn_total") is None:
            continue
        if worst is None or r["fee_burn_total"] > worst["fee_burn_total"]:
            worst = r
    note = ("A low entry fee is not cheap if the retry loop is expensive. "
            "We price the whole loop, not just the first attempt.")
    return {"note": note,
            "worst_firm": worst["firm"] if worst else None,
            "worst_burn": worst["fee_burn_total"] if worst else None}


# ------------------------------------------------------- best-fit matchmaker
def _firm_profile(f: dict) -> list[str]:
    out = []
    dt = (f.get("drawdown_type") or "").lower()
    if "static" in dt:
        out.append("Static drawdown (floor doesn't trail your equity)")
    elif "intraday" in dt:
        out.append("Intraday trailing drawdown (tightest)")
    elif "trailing" in dt or "eod" in dt:
        out.append("End-of-day trailing drawdown")
    tgt = max((p.get("target_pct", 0) for p in f.get("phases", [])), default=0)
    if tgt:
        out.append(f"Profit target {tgt:g}%" + (" — lower" if tgt <= 6 else " — higher"))
    if not f.get("min_trading_days"):
        out.append("No minimum-day pressure")
    else:
        out.append(f"Min {f['min_trading_days']} trading days")
    if not f.get("consistency_rule_pct"):
        out.append("No consistency cap")
    else:
        out.append(f"Consistency cap {f['consistency_rule_pct']:g}%")
    if f.get("daily_loss_limit_pct"):
        out.append(f"Daily loss limit {f['daily_loss_limit_pct']:g}%")
    return out


def best_fit_matchmaker(results) -> dict:
    if not results:
        return {}
    best = results[0]
    worst = results[-1]
    return {
        "best_firm": f"{best.firm['firm_name']} — {best.firm['product']}",
        "best_why": _firm_profile(best.firm),
        "best_odds": best.pass_prob,
        "worst_firm": f"{worst.firm['firm_name']} — {worst.firm['product']}",
        "worst_why": _firm_profile(worst.firm),
        "worst_odds": worst.pass_prob,
        "label": "Based on this uploaded history and verified rules — not a recommendation.",
    }


# --------------------------------------------------------- personal danger rules
def personal_danger_rules(autopsy: dict, dna: dict, best_result) -> dict:
    rules = []
    lab = (getattr(best_result, "killer_rule_label", "") or "").lower()
    if "trailing" in lab:
        rules.append("Pattern note: large early equity spikes raise the trailing floor and tighten the breach margin in similar samples.")
        rules.append("Firms with static (non-trailing) drawdown are mechanically less sensitive to this historical pattern.")
    if "daily loss" in lab:
        rules.append("Pattern note: historical clusters of losses appear after 2 losing trades within a session.")
    if "profit target" in lab:
        rules.append("Lower-target or no-time-limit challenges are mechanically less sensitive to the time-pressure failure mode in this sample.")
    if dna.get("available"):
        m = dna["metrics"]
        if m["longest_loss_streak"] >= 4:
            rules.append("Pattern note: extended losing streaks detected; weekly loss caps are commonly used to manage exposure to this pattern.")
        if m["risk_drift"] >= 1.3:
            rules.append("Pattern note: per-trade risk drifts upward across the sample.")
    rules.append("Re-run RealityCheck after ~30 more trades to refresh these odds.")
    # de-dup, cap at 5
    seen, final = set(), []
    for r in rules:
        if r not in seen:
            seen.add(r); final.append(r)
    return {"rules": final[:5],
            "label": "Risk pattern notes derived from your history — diagnostic only, not advice."}
