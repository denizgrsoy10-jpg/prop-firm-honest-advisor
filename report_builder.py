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
import insights
import sequence_risk
import rule_interaction
import regime_analysis
import bayesian
import kelly


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
            "retry_danger": insights.retry_danger(r.pass_prob),
            "note": r.note,
            "verification_status": r.firm.get("verification_status"),
            "breach_breakdown": r.breach_breakdown,
        })

    best = results[0]
    # Scale P/L to the selected account size before what-if (same logic as simulate_all)
    from simulator import _scaled_pnls_for
    _wif_pnls = _scaled_pnls_for(daily_pnls, best.firm)
    whatif = what_if_table(_wif_pnls, best.firm)
    firms = [r.firm for r in results]

    # --- Wave 1 insight modules (all honest diagnostics, never advice) -------
    autopsy = insights.killer_rule_autopsy(best)
    dna = insights.risk_dna(daily_pnls, preview["data"])

    # --- Kelly sizing layer (trader-level edge & growth-optimal fraction) -----
    _kelly = kelly.kelly_analysis(daily_pnls)

    # --- Bayesian posterior sharpness on the best-fit firm's pass odds --------
    _n_trades = preview["data"].get("n_trades")
    _bayes = {
        "best_interval": bayesian.credible_interval_pct(best.pass_prob, _n_trades),
        "band_width_pct": round(bayesian.posterior_width(best.pass_prob, _n_trades) * 100, 1),
        "trades_to_halve": bayesian.trades_to_halve_band(best.pass_prob, _n_trades),
        "n_trades": _n_trades,
    }

    # --- Regime layer (trader-level; uses raw history, firm-independent) -------
    _regime = regime_analysis.regime_report(daily_pnls)

    # --- Rule interaction layer (how rules compound for best-fit firm) --------
    _ri = rule_interaction.rule_interaction_analysis(
        _wif_pnls, best.firm, phase_index=0)

    # --- Path-dependency layer (sequence risk on the best-fit ruleset) -------
    # Uses the size-scaled P/L so it matches the odds shown for that firm.
    _seq = sequence_risk.sequence_risk(_wif_pnls, best.firm, phase_index=0)
    _streak = sequence_risk.streak_profile(daily_pnls)

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
        "data_audit": insights.data_quality_audit(preview["data"], daily_pnls),
        "autopsy": autopsy,
        "risk_dna": dna,
        "fee_burn_headline": insights.fee_burn_headline(firm_rows),
        "matchmaker": insights.best_fit_matchmaker(results),
        "danger_rules": insights.personal_danger_rules(autopsy, dna, best),
        "kelly": ({
            "edge_grade": _kelly.edge_grade,
            "win_rate": _kelly.win_rate,
            "payoff_ratio": _kelly.payoff_ratio,
            "kelly_fraction": _kelly.kelly_fraction,
            "recommended_fraction_label": _kelly.recommended_fraction_label,
            "headline": _kelly.headline,
            "detail": _kelly.detail,
            "sizing_note": _kelly.sizing_note,
        } if _kelly else None),
        "bayesian": _bayes,
        "regime": _regime,
        "rule_interaction": ({
            "compound_breach_pct": _ri.compound_breach_pct,
            "solo_breach_pct": _ri.solo_breach_pct,
            "spike_then_floor_pct": _ri.spike_then_floor_pct,
            "consistency_ceiling_pct": _ri.consistency_ceiling_pct,
            "double_window_pct": _ri.double_window_pct,
            "active_rules": _ri.active_rules,
            "trap_labels": _ri.trap_labels,
            "compound_label": _ri.compound_label,
        } if _ri else {"compound_label": None, "trap_labels": []}),
        "sequence_risk": ({
            "pass_rate_shuffled": _seq.pass_rate_shuffled,
            "worst_quartile_pass": _seq.worst_quartile_pass,
            "order_sensitivity": _seq.order_sensitivity,
            "dominant_breach_label": _seq.dominant_breach_label,
            "label": _seq.label,
            "streak": _streak,
        } if _seq else {"streak": _streak, "label": None}),
        "disclaimer": ("Statistical simulation only. Not financial, investment or "
                       "trading advice. No outcome with any firm is guaranteed."),
    }
