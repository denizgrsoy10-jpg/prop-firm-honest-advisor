"""
own_account.py
--------------
Own Account RealityCheck — V0.

Same engine, different question:
  Prop Firm mode   : "Can I pass this challenge?"
  Own Account mode : "Can my own account survive my trading?"

V0 outputs — every output is statistical risk diagnostics, never advice:
  - Account Survival Score (0-100) + confidence label
  - Drawdown Risk Bands (Low / Medium / High / Severe — NO sharp percentage)
  - Killer Behavior (reused from Risk DNA, behavioral diagnostics)
  - Margin Pressure (input-driven, band-only)
  - What-if Lab (scenario impact on drawdown band)
  - Personal Risk-Control Checklist (pattern-note style)
  - Instrument Fit / Session Risk : V0 returns "not yet available" gracefully
    (extended parser ingestion planned for V1).

Hard rules enforced everywhere in this module:
  - No sharp probabilities of account failure. Bands only.
  - No imperative phrasing. No "reduce lot", no "stop trading", no "avoid X".
  - Every number carries 'Estimated from uploaded history; not a forecast.'
  - Limited-confidence labels for thin samples.
"""
from __future__ import annotations
from datetime import date

import insights
from tracking import make_report_id, confidence_from


SCENARIO_LABEL = "Scenario analysis, not advice."
FORECAST_LABEL = "Estimated from uploaded history; not a forecast."
NOT_ADVICE_LABEL = "Statistical risk diagnostics only. Not trading advice."


# --- helpers ----------------------------------------------------------------

def _max_drawdown(daily_pnls, start_balance):
    """Peak-to-trough drawdown on the cumulative equity curve.
    Returns (max_dd_dollars, max_dd_ratio_of_start_balance, equity_curve)."""
    eq = [float(start_balance)]
    cum = float(start_balance)
    for p in daily_pnls:
        cum += float(p)
        eq.append(cum)
    peak = eq[0]
    max_dd = 0.0
    for v in eq:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return max_dd, (max_dd / max(start_balance, 1e-9)), eq


def _band_for_ratio(r):
    """Coarse band from a drawdown ratio. Intentionally coarse to avoid
    false precision."""
    if r < 0.10:
        return "Low"
    if r < 0.25:
        return "Medium"
    if r < 0.50:
        return "High"
    return "Severe"


def _confidence(n_days):
    if n_days >= 60:
        return "High"
    if n_days >= 30:
        return "Medium"
    return "Limited"


# --- survival score ---------------------------------------------------------

def survival_score(daily_pnls, start_balance, meta):
    """0-100 score. Higher = historical pattern survived better against own
    account; lower = more drawdown pressure. Coarse on purpose, with a
    confidence label. Never presented as a probability."""
    if not daily_pnls or start_balance <= 0:
        return {"score": None, "band": "Insufficient data",
                "confidence": "Limited",
                "forecast_label": FORECAST_LABEL}

    _, max_dd_r, eq = _max_drawdown(daily_pnls, start_balance)
    final_r = eq[-1] / start_balance
    prof_days = sum(1 for p in daily_pnls if p > 0)
    prof_frac = prof_days / max(len(daily_pnls), 1)

    # longest losing streak penalty
    streak = best = 0
    for p in daily_pnls:
        if p < 0:
            streak += 1
            if streak > best:
                best = streak
        else:
            streak = 0
    streak_pen = min(best, 10) * 3.0  # cap at -30

    score = 50.0
    score += 25.0 * min(max(final_r - 1.0, -1.0), 1.0)
    score += 30.0 * (prof_frac - 0.5)
    score -= 30.0 * min(max_dd_r, 1.0)
    score -= streak_pen
    score = max(0.0, min(100.0, score))

    return {
        "score": int(round(score)),
        "band": _band_for_ratio(max_dd_r),
        "observed_max_dd_band": _band_for_ratio(max_dd_r),
        "confidence": _confidence(meta.get("n_days", len(daily_pnls))),
        "forecast_label": FORECAST_LABEL,
    }


# --- drawdown risk bands ----------------------------------------------------

def drawdown_bands(daily_pnls, start_balance):
    """Per-threshold sensitivity band. No sharp probability output.
    For each fixed threshold (10/20/30/50%), report whether observed historical
    max drawdown breached it and how close-to-the-edge the sample sat."""
    _, max_dd_r, _ = _max_drawdown(daily_pnls, start_balance)
    rows = []
    for th in (0.10, 0.20, 0.30, 0.50):
        breached = max_dd_r >= th
        if breached:
            band = "Severe" if max_dd_r >= th * 1.5 else "High"
        else:
            margin = (th - max_dd_r) / max(th, 1e-9)
            if margin >= 0.75:
                band = "Low"
            elif margin >= 0.35:
                band = "Medium"
            else:
                band = "High"   # tight margin = elevated sensitivity
        rows.append({
            "threshold_pct": int(th * 100),
            "band": band,
            "breached_in_history": bool(breached),
            "label": FORECAST_LABEL,
        })
    return {
        "rows": rows,
        "observed_max_dd_band": _band_for_ratio(max_dd_r),
        "label": NOT_ADVICE_LABEL,
    }


# --- killer behavior (reuse Risk DNA from insights) -------------------------

def killer_behavior(daily_pnls, meta):
    dna = insights.risk_dna(daily_pnls, meta)
    if not dna.get("available"):
        return {"available": False,
                "note": dna.get("note",
                                "Not enough data for a behavioral read."),
                "label": NOT_ADVICE_LABEL}
    m = dna["metrics"]
    return {
        "available": True,
        "behavior": dna["most_dangerous_behavior"],
        "note": dna["behavior_note"],
        "metrics": {
            "longest_loss_streak": m["longest_loss_streak"],
            "loss_streak_sensitivity": m["loss_streak_sensitivity"],
            "profit_concentration": m["profit_concentration"],
            "concentration_label": m["concentration_label"],
            "drift_label": m["drift_label"],
        },
        "label": NOT_ADVICE_LABEL,
    }


# --- margin pressure (input-driven) -----------------------------------------

def margin_pressure(daily_pnls, start_balance, leverage, stop_out_pct=None):
    """V0: observed equity floor vs typical stop-out percentage.
    Always band-only, never a probability of liquidation."""
    if start_balance <= 0 or leverage <= 0 or not daily_pnls:
        return {"available": False,
                "note": ("Margin pressure estimate is limited because "
                         "starting balance, leverage, or trade history is "
                         "incomplete."),
                "label": NOT_ADVICE_LABEL}

    max_dd, max_dd_r, _ = _max_drawdown(daily_pnls, start_balance)
    floor_ratio = (start_balance - max_dd) / max(start_balance, 1e-9)
    stop = (stop_out_pct or 50) / 100.0
    headroom = floor_ratio - stop

    if headroom < 0:
        headroom_band = "Severe"
    elif headroom < 0.10:
        headroom_band = "High"
    elif headroom < 0.30:
        headroom_band = "Medium"
    else:
        headroom_band = "Low"

    return {
        "available": True,
        "leverage": float(leverage),
        "stop_out_pct": int(stop * 100),
        "observed_floor_pct": round(floor_ratio * 100, 1),
        "margin_pressure_band": _band_for_ratio(1.0 - floor_ratio),
        "stopout_headroom_band": headroom_band,
        "label": FORECAST_LABEL,
    }


# --- what-if scenarios ------------------------------------------------------

def what_if_scenarios(daily_pnls, start_balance):
    """Scale historical daily P/L by factors and recompute drawdown band.
    No sharp probability — only band shift."""
    presets = [1.00, 0.80, 0.65, 0.50]
    rows = []
    for f in presets:
        scaled = [p * f for p in daily_pnls]
        _, max_dd_r, _ = _max_drawdown(scaled, start_balance)
        rows.append({
            "risk_pct": int(round(f * 100)),
            "observed_dd_band": _band_for_ratio(max_dd_r),
            "scenario_label": SCENARIO_LABEL,
        })
    return {
        "rows": rows,
        "label": ("Scenario impact on observed drawdown band if historical "
                  "trade size had been scaled. Scenario analysis, not advice."),
    }


# --- personal risk-control checklist ----------------------------------------

def risk_control_checklist(killer_behav, dd_bands):
    """Pattern-note style. No imperatives. No 'reduce X' or 'avoid Y'."""
    items = []
    obs_band = dd_bands.get("observed_max_dd_band", "Medium")

    if obs_band in ("High", "Severe"):
        items.append(
            f"Pattern note: observed historical drawdown band is {obs_band}; "
            "scenarios that scale per-trade risk down shift this band "
            "downward in this sample.")

    if killer_behav.get("available"):
        m = killer_behav["metrics"]
        if m.get("longest_loss_streak", 0) >= 4:
            items.append(
                "Pattern note: extended losing streaks detected "
                f"({m['longest_loss_streak']} days). Weekly loss caps are "
                "commonly used to manage exposure to this pattern.")
        if str(m.get("concentration_label", "")).lower().startswith("high"):
            items.append(
                "Pattern note: profit is concentrated in a small number of "
                "sessions; removing a single best day would materially shift "
                "the equity curve in this sample.")
        if str(m.get("drift_label", "")).lower() in ("high", "medium"):
            items.append(
                "Pattern note: per-trade risk drifts upward across the "
                "sample.")

    items.append(
        "Re-run RealityCheck after ~30 more trades to refresh these "
        "diagnostics.")

    # dedup + cap
    seen, final = set(), []
    for it in items:
        if it not in seen:
            seen.add(it)
            final.append(it)
    return {"items": final[:5], "label": NOT_ADVICE_LABEL}


# --- full Own Account report assembler --------------------------------------

def build_own_account_report(daily_pnls, meta, *,
                             start_balance: float,
                             leverage: float,
                             stop_out_pct=None,
                             account_currency: str = "USD",
                             report_id: str | None = None) -> dict:
    """One report dict the renderer and the PDF builder consume."""
    rid = report_id or make_report_id()
    audit = insights.data_quality_audit(meta, daily_pnls)
    conf = confidence_from(meta)

    ss = survival_score(daily_pnls, start_balance, meta)
    bands = drawdown_bands(daily_pnls, start_balance)
    kb = killer_behavior(daily_pnls, meta)
    mp = margin_pressure(daily_pnls, start_balance, leverage, stop_out_pct)
    wif = what_if_scenarios(daily_pnls, start_balance)
    chk = risk_control_checklist(kb, bands)

    return {
        "report_type": "own_account",
        "report_id": rid,
        "generated": str(date.today()),
        "confidence": conf,
        "account": {
            "starting_balance": float(start_balance),
            "currency": account_currency,
            "leverage": float(leverage),
            "stop_out_pct": stop_out_pct,
        },
        "data_audit": audit,
        "survival_score": ss,
        "drawdown_bands": bands,
        "killer_behavior": kb,
        "instrument_fit": {
            "available": False,
            "note": ("Instrument-level analysis is not yet available — the "
                     "current parser does not extract per-symbol fields. "
                     "Extended ingestion is planned."),
        },
        "session_risk": {
            "available": False,
            "note": ("Session-level analysis requires intraday timestamps. "
                     "The current parser stores trades at day-level "
                     "granularity only. Extended ingestion is planned."),
        },
        "margin_pressure": mp,
        "what_if": wif,
        "checklist": chk,
        "disclaimer": ("Statistical simulation only. Not financial, investment "
                       "or trading advice. No outcome with any account, "
                       "broker, or instrument is guaranteed."),
    }
