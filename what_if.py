"""
what_if.py
----------
Estimates how a trader's pass odds would change if they scaled their risk.

V1 approximation: scaling risk per trade is modelled as scaling each day's net
P/L by the same factor. This is a first-order approximation, NOT a guarantee.
Every what-if number must be presented with the "estimated" label below.
"""

from __future__ import annotations
from simulator import simulate_firm

WHATIF_LABEL = ("Estimated what-if scenario — based on scaling your historical "
                "daily risk. A first-order approximation, not a guarantee.")

DEFAULT_PRESETS = [1.00, 0.80, 0.65, 0.50]


def scale_pnls(daily_pnls: list[float], factor: float) -> list[float]:
    return [p * factor for p in daily_pnls]


def what_if_table(daily_pnls: list[float], firm: dict,
                  presets=DEFAULT_PRESETS, iters: int = 1500, seed: int = 7) -> list[dict]:
    """
    Returns rows: [{risk_pct, pass_prob, killer_rule_label}], one per preset.
    Lower risk usually reduces drawdown breaches but can also slow you toward
    the target — the table shows the real trade-off rather than a one-way story.
    """
    rows = []
    for f in presets:
        scaled = scale_pnls(daily_pnls, f)
        res = simulate_firm(scaled, firm, iters=iters, seed=seed)
        rows.append({
            "risk_pct": int(round(f * 100)),
            "pass_prob": res.pass_prob,
            "killer_rule_label": res.killer_rule_label,
        })
    return rows
