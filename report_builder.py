"""
report_builder.py
-----------------
Turns raw simulation results into the two payloads the product sells:

  build_preview(...)  -> the free teaser (best/worst firm, odds range, killer
                         rule, go/wait/skip verdict)
  build_full_report(...) -> the paid report (every firm, killer rule per firm,
                         expected fee burn, what-if table, daily breakdown,
                         equity curve)
"""

from __future__ import annotations
from datetime import date

from simulator import simulate_all, verdict_for
from rules_engine import ruleset_version
from what_if import what_if_table, WHATIF_LABEL
from tracking import make_report_id, confidence_from


def _expected_fee_burn(fee, pass_prob):
    """Expected total fees = fee * expected attempts (1/p). Honest about low p."""
    if pass_prob <= 0.0:
        return None, "Pass odds near zero — no fee makes statistical sense here."
    attempts = 1.0 / pass_prob
    total = fee * attempts
    if attempts >= 5:
        msg = f"~{attempts:.1f} attempts on average (${total:,.0f}) — an expensive habit."
    elif attempts >= 2:
        msg = f"~{attempts:.1f} attempts on average (${total:,.0f})."
    else:
        msg = f"~{attempts:.1f} attempt on average (${total:,.0f})."
    return total, msg


def build_preview(daily_pnls, firms, meta, iters=2000):
    results = simulate_all(daily_pnls, firms, iters=iters)
    best = results[0]
    worst = results[-1]
    low = min(r.pass_prob for r in results)
    high = max(r.pass_prob for r in results)
    return {
        "generated": str(date.today()),
        "data": meta,
        "best_firm": f"{best.firm['firm_name']} — {best.firm['product']}",
        "best_prob": best.pass_prob,
        "worst_firm": f"{worst.firm['firm_name']} — {worst.firm['product']}",
        "worst_prob": worst.pass_prob,
        "odds_range": (low, high),
        "killer_rule": best.killer_rule_label,
        "verdict": verdict_for(best.pass_prob),
        "_results": results,  # carried internally for the full report
    }


def build_full_report(preview, daily_pnls, report_id=None):
    results = preview["_results"]
    firm_rows = []
    for r in results:
        fee = r.firm.get("fee", 0) or 0
        burn_total, burn_msg = _expected_fee_burn(fee, r.pass_prob)
        firm_rows.append({
            "firm": f"{r.firm['firm_name']} — {r.firm['product']}",
            "pass_prob": r.pass_prob,
            "verdict": verdict_for(r.pass_prob),
            "killer_rule": r.killer_rule_label,
            "fee": fee,
            "fee_burn_total": burn_total,
            "fee_burn_msg": burn_msg,
            "note": r.note,
            "verification_status": r.firm.get("verification_status"),
            "breach_breakdown": r.breach_breakdown,
        })

    best = results[0]
    whatif = what_if_table(daily_pnls, best.firm)
    firms = [r.firm for r in results]

    return {
        "report_id": report_id or make_report_id(),
        "ruleset_version": ruleset_version(firms),
        "simulation_date": preview["generated"],
        "confidence": confidence_from(preview["data"]),
        "generated": preview["generated"],
        "data": preview["data"],
        "firm_rows": firm_rows,
        "best_firm": preview["best_firm"],
        "best_pass_prob": best.pass_prob,
        "best_killer_rule": best.killer_rule_label,
        "equity_curve": best.sample_curve,
        "equity_start": float(best.firm["account_size"]),
        "what_if": {
            "firm": preview["best_firm"],
            "label": WHATIF_LABEL,
            "rows": whatif,
        },
        "disclaimer": ("Statistical simulation only. Not financial, investment or "
                       "trading advice. No outcome with any firm is guaranteed."),
    }
