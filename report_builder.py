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
import leverage_map as leverage_map_mod
import funded_survival as funded_survival_mod
import consistency_risk as consistency_risk_mod
import robustness as robustness_mod


def _expected_fee_burn(fee, pass_prob, n_effective=None):
    """Expected total fees across the retry loop, shown as a RANGE.

    Expected attempts to pass once is 1/p, but p itself is uncertain (a Bayesian
    credible interval, not a point). So instead of a single false-precision
    figure ("$8,181"), we propagate the odds uncertainty into the attempt count
    and total cost: a high p gives few attempts (low end), a low p gives many
    (high end). The point estimate is kept only as a midpoint for ranking.
    """
    if pass_prob <= 0.0:
        return None, "Pass odds near zero — no fee makes statistical sense here."

    # Point estimate (used for ranking / sorting only)
    attempts_mid = 1.0 / pass_prob
    total_mid = fee * attempts_mid

    # Propagate odds uncertainty: attempts = 1/p, so the LOW odds bound gives
    # the HIGH attempt count and vice-versa.
    lo_p, hi_p = bayesian.credible_interval(pass_prob, n_effective)
    # Guard tiny lower bounds so the high end stays finite and honest.
    lo_p_safe = max(lo_p, 0.01)
    attempts_hi = 1.0 / lo_p_safe   # worst-case: many attempts
    attempts_lo = 1.0 / hi_p        # best-case: few attempts
    cost_lo = fee * attempts_lo
    cost_hi = fee * attempts_hi

    def _fmt_attempts(a):
        return f"{a:.0f}" if a >= 2 else f"{a:.1f}"

    # Round costs to ~2 significant figures so we never imply dollar precision.
    def _round_sig(x, sig=2):
        if x <= 0:
            return 0
        import math
        d = sig - int(math.floor(math.log10(abs(x)))) - 1
        return round(x, d)

    c_lo = _round_sig(cost_lo)
    c_hi = _round_sig(cost_hi)

    a_lo_s = _fmt_attempts(attempts_lo)
    a_hi_s = _fmt_attempts(attempts_hi)

    # Severity wording keyed off the midpoint, but numbers shown as ranges.
    if attempts_mid >= 5:
        tail = " — an expensive loop once you account for the odds range."
    else:
        tail = ""

    if c_lo >= 1000 or c_hi >= 1000:
        cost_str = f"${c_lo:,.0f}–${c_hi:,.0f}"
    else:
        cost_str = f"${c_lo:,.0f}–${c_hi:,.0f}"

    msg = (f"~{a_lo_s}–{a_hi_s} attempts (≈{cost_str}), depending where your true "
           f"odds sit in their range{tail}")

    # Return the midpoint total for ranking, plus the range message.
    return total_mid, msg


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


def _build_reality_summary(firm_rows, best, results, _leverage, _robust,
                           confidence, n_trades):
    """Assemble the shareable Reality Summary + a stability-warning card.

    This is the first screen a reader (or an influencer screenshot) sees: the
    handful of facts that matter, plus an explicit reconciliation of the two
    different trust signals (data confidence vs. self-validation stability) so
    a strong fit alongside a low stability score never reads as a contradiction.
    """
    # Highest and lowest fit firms (results are sorted best-first)
    best_row = firm_rows[0] if firm_rows else None
    worst_row = firm_rows[-1] if firm_rows else None

    def _range_str(pass_prob):
        return bayesian.credible_interval_pct(pass_prob, n_trades)

    highest_fit = None
    if best_row:
        highest_fit = {
            "firm": best_row["firm"],
            "range": _range_str(best_row["pass_prob"]),
            "verdict": best_row["verdict"],
        }
    severe_mismatch = None
    if worst_row and worst_row is not best_row:
        severe_mismatch = {
            "firm": worst_row["firm"],
            "range": _range_str(worst_row["pass_prob"]),
            "verdict": worst_row["verdict"],
        }

    # Dominant blocker + whether failure modes contradict
    dominant_blocker = None
    blocker_count = None
    contradiction = False
    if _leverage:
        dominant_blocker = _leverage.dominant_blocker_label
        blocker_count = (f"{_leverage.firms_blocked_by_dominant} of "
                         f"{_leverage.total_firms}")
        contradiction = bool(_leverage.contradiction)

    # Stability trust from out-of-sample validation
    stability_trust = None
    stability_label = None
    if _robust and _robust.available:
        stability_trust = _robust.stability      # stable | moderate | fragile
        stability_label = {
            "stable": "Stable",
            "moderate": "Moderate",
            "fragile": "Low / Fragile",
        }.get(_robust.stability, _robust.stability)

    # Main warning line: opposite failure modes is the headline risk when present
    if contradiction:
        main_warning = ("Same behavior creates opposite failure modes across "
                        "rulesets — there is no single fix.")
    else:
        main_warning = (f"{dominant_blocker} is the broadest blocker "
                        f"({blocker_count} firms)." if dominant_blocker else
                        "See the per-ruleset breakdown below.")

    # --- Stability warning card -----------------------------------------------
    # Only fires when fit looks strong but the history is not stable, i.e. the
    # exact situation that would otherwise read as a contradiction.
    stability_warning = None
    strong_fit = bool(best_row and best_row["pass_prob"] >= 0.50)
    if stability_trust == "fragile":
        warn_headline = ("Strong fit \u00b7 Low stability trust" if strong_fit
                         else "Low stability trust")
        stability_warning = {
            "headline": warn_headline,
            "body": (
                "This history shows "
                + ("a strong ruleset fit, but low stability trust. "
                   if strong_fit else "low stability trust. ")
                + "Your earlier and recent halves behave very differently, so "
                "treat the headline ranges as provisional until more trades are "
                "added. Data confidence and stability trust measure two different "
                "things: confidence reflects how many trades you have, while "
                "stability reflects whether those trades tell a consistent story. "
                "You can have enough data to form a range and still find that the "
                "range is unstable."),
        }
    elif stability_trust == "moderate" and strong_fit:
        stability_warning = {
            "headline": "Strong fit \u00b7 Moderate stability trust",
            "body": (
                "This history shows a strong ruleset fit with moderate stability "
                "trust. Your earlier and recent trading differ somewhat, so the "
                "headline ranges are a reasonable summary but not a precise one."),
        }

    return {
        "highest_fit": highest_fit,
        "severe_mismatch": severe_mismatch,
        "dominant_blocker": dominant_blocker,
        "dominant_blocker_count": blocker_count,
        "killer_rule": best.killer_rule_label,
        "data_confidence": confidence,
        "stability_trust": stability_trust,
        "stability_trust_label": stability_label,
        "main_warning": main_warning,
        "disclaimer": "Diagnostic only — not a recommendation.",
        "stability_warning": stability_warning,
    }


def build_full_report(preview, daily_pnls, report_id=None):
    results = preview["_results"]
    _n_tr = preview["data"].get("n_trades")
    firm_rows = []
    for r in results:
        fee = r.firm.get("fee", 0) or 0
        burn_total, burn_msg = _expected_fee_burn(fee, r.pass_prob, _n_tr)
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

    # --- Cross-firm leverage map (needs the full firm list from results) ------
    _lev_firms = [r.firm for r in results]
    _leverage = leverage_map_mod.leverage_map(daily_pnls, _lev_firms)

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

    # --- Out-of-sample validation layer (the model checking itself) ----------
    # Computed early so the regime read can defer to it: if the two halves of
    # the history diverge, regime must not call the record stationary.
    _robust = robustness_mod.best_robustness(results, daily_pnls)
    _robust_dict = ({"stability": _robust.stability, "gap": _robust.gap}
                    if _robust and _robust.available else None)

    # --- Regime layer (trader-level; uses raw history, firm-independent) -------
    # Passes the out-of-sample result so regime trust and self-validation agree.
    _regime = regime_analysis.regime_report(daily_pnls, robustness=_robust_dict)

    # --- Rule interaction layer (how rules compound for best-fit firm) --------
    _ri = rule_interaction.rule_interaction_analysis(
        _wif_pnls, best.firm, phase_index=0)

    # --- Path-dependency layer (sequence risk on the best-fit ruleset) -------
    # Uses the size-scaled P/L so it matches the odds shown for that firm.
    _seq = sequence_risk.sequence_risk(_wif_pnls, best.firm, phase_index=0)
    _streak = sequence_risk.streak_profile(daily_pnls)

    # --- Funded survival layer (what happens AFTER the pass) ------------------
    # Models the funded stage on the best-fit firm: survival curve over time +
    # first-payout race. The funded account is a separate game with its own
    # rules, so passing odds alone overstate the real expectation.
    _funded = funded_survival_mod.best_funded_target(
        results, {f["firm_name"]: f for f in firms}, daily_pnls)

    # --- Consistency cap layer (the "made money but still failed" trap) ------
    # Many firms cap how much of total profit a single day can represent.
    # This is a separate elimination path from drawdown/target rules.
    _consistency = consistency_risk_mod.best_consistency_target(
        results, {f["firm_name"]: f for f in firms}, daily_pnls)

    # --- Reality Summary (shareable first screen + stability reconciliation) --
    _reality = _build_reality_summary(
        firm_rows, best, results, _leverage, _robust,
        confidence_from(preview["data"]), _n_tr)

    return {
        "reality_summary": _reality,
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
        "leverage_map": ({
            "dominant_blocker_label": _leverage.dominant_blocker_label,
            "firms_blocked_by_dominant": _leverage.firms_blocked_by_dominant,
            "total_firms": _leverage.total_firms,
            "dominant_firm_names": _leverage.dominant_firm_names,
            "contradiction": _leverage.contradiction,
            "aggression_firms": _leverage.aggression_firms,
            "caution_firms": _leverage.caution_firms,
            "headline": _leverage.headline,
            "detail": _leverage.detail,
        } if _leverage else None),
        "kelly": ({
            "edge_grade": _kelly.edge_grade,
            "win_rate": _kelly.win_rate,
            "payoff_ratio": _kelly.payoff_ratio,
            "kelly_fraction": _kelly.kelly_fraction,
            "kelly_low": _kelly.kelly_low,
            "kelly_high": _kelly.kelly_high,
            "win_rate_low": _kelly.win_rate_low,
            "win_rate_high": _kelly.win_rate_high,
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
        "funded_survival": ({
            "firm": _funded.firm,
            "account_size": _funded.account_size,
            "dd_pct": _funded.dd_pct,
            "dd_is_trailing": _funded.dd_is_trailing,
            "horizons": _funded.horizons,
            "survival_rates": _funded.survival_rates,
            "median_days_survived": _funded.median_days_survived,
            "payout_threshold": _funded.payout_threshold,
            "profit_split": _funded.profit_split,
            "min_days": _funded.min_days,
            "reach_payout_rate": _funded.reach_payout_rate,
            "blow_before_payout_rate": _funded.blow_before_payout_rate,
            "avg_first_payout": _funded.avg_first_payout,
            "headline": _funded.headline,
            "detail": _funded.detail,
            "label": _funded.label,
        } if _funded and _funded.available else None),
        "consistency_risk": ({
            "firm": _consistency.firm,
            "cap_pct": _consistency.cap_pct,
            "cap_source": _consistency.cap_source,
            "applies": _consistency.applies,
            "pass_target_rate": _consistency.pass_target_rate,
            "consistency_kill_rate": _consistency.consistency_kill_rate,
            "clean_pass_rate": _consistency.clean_pass_rate,
            "best_day_share": _consistency.best_day_share,
            "headroom": _consistency.headroom,
            "headline": _consistency.headline,
            "detail": _consistency.detail,
            "label": _consistency.label,
        } if _consistency and _consistency.available else None),
        "robustness": ({
            "firm": _robust.firm,
            "n_days": _robust.n_days,
            "train_days": _robust.train_days,
            "test_days": _robust.test_days,
            "train_pass": _robust.train_pass,
            "test_pass": _robust.test_pass,
            "full_pass": _robust.full_pass,
            "gap": _robust.gap,
            "stability": _robust.stability,
            "trust_score": _robust.trust_score,
            "headline": _robust.headline,
            "detail": _robust.detail,
            "label": _robust.label,
        } if _robust and _robust.available else None),
        "disclaimer": ("Statistical simulation only. Not financial, investment or "
                       "trading advice. No outcome with any firm is guaranteed."),
    }
