"""
leverage_map.py
===============
Sixth layer of heavy lifting: cross-firm leverage-point analysis.

WHY THIS EXISTS:
The other layers analyse the trader against ONE ruleset at a time. But a trader
staring at nine firms - most labelled "high mismatch" - has no way to see the
PATTERN ACROSS firms:

  - Is the SAME rule blocking them everywhere, or different rules at different
    firms? If one rule dominates the failures across many firms, fixing that
    single thing unlocks all of them at once - a single leverage point.
  - Worse and more useful: the dominant blocker can CONTRADICT itself across
    firms. At trailing-drawdown firms the trader fails by breaching the floor
    (they need to be MORE cautious); at static firms they fail by not reaching
    the target in time (they need to be MORE aggressive). No trader can see
    that they must pull in two opposite directions for two groups of firms.

This module runs the existing rule checker across every firm, attributes the
dominant failure mode per firm, then aggregates:

  1) SINGLE LEVERAGE POINT - the one rule that, if addressed, would improve the
     most firms, with a count of how many and which ones.
  2) CONTRADICTION MAP - whether the trader faces opposite problems (target vs
     drawdown) at different firm groups, which is the single most important
     thing a multi-firm view can reveal and a single-firm tool never will.

Pure analysis on top of evaluate_phase - no new rule logic. Diagnostic only.
"""

from __future__ import annotations
import random
from collections import Counter
from dataclasses import dataclass

from rules_engine import evaluate_phase, BREACH_LABELS


# Group breach reasons into the two strategic directions they imply.
_TARGET_SIDE = {"target_not_reached", "min_trading_days"}
_RISK_SIDE = {"trailing_drawdown", "max_drawdown", "static_drawdown",
              "daily_loss_limit", "consistency_rule"}


def _direction(breach_key: str) -> str:
    if breach_key in _TARGET_SIDE:
        return "need_more_aggression"   # not reaching target / not enough days
    if breach_key in _RISK_SIDE:
        return "need_more_caution"      # breaching a risk limit
    return "other"


@dataclass
class LeverageMap:
    dominant_blocker_key: str
    dominant_blocker_label: str
    firms_blocked_by_dominant: int
    total_firms: int
    dominant_firm_names: list
    contradiction: bool
    aggression_firms: list       # firms where the trader needs to reach target faster
    caution_firms: list          # firms where the trader breaches a risk limit
    headline: str
    detail: str
    disclaimer: str = ("Cross-firm leverage analysis from your uploaded history. "
                       "Diagnostic only - not financial advice.")


def leverage_map(daily_pnls, firms, phase_index: int = 0,
                 iters: int = 1500, seed: int = 42):
    """Attribute the dominant failure mode per firm and find the leverage point."""
    if len(daily_pnls) < 6 or len(firms) < 2:
        return None

    rng = random.Random(seed)
    dominant_by_firm = {}        # firm_name -> dominant breach key
    horizon = min(len(daily_pnls), 28)

    for f in firms:
        breaches = {}
        passes = 0
        for _ in range(iters):
            path = [rng.choice(daily_pnls) for _ in range(horizon)]
            res = evaluate_phase(path, f, phase_index)
            if res.passed:
                passes += 1
            elif res.breach_reason:
                breaches[res.breach_reason] = breaches.get(res.breach_reason, 0) + 1
        # Only attribute a blocker if the firm fails meaningfully often
        if breaches and passes < iters * 0.85:
            dominant_by_firm[f["firm_name"] + " - " + f.get("product", "")] = \
                max(breaches, key=breaches.get)

    if not dominant_by_firm:
        return LeverageMap(
            dominant_blocker_key="none",
            dominant_blocker_label="No dominant blocker",
            firms_blocked_by_dominant=0,
            total_firms=len(firms),
            dominant_firm_names=[],
            contradiction=False,
            aggression_firms=[],
            caution_firms=[],
            headline=("No firm blocks you often enough to flag a single leverage "
                      "point - your pass odds are broadly healthy."),
            detail=("Across these firms there's no one rule doing most of the "
                    "damage. That's a good sign: there isn't a single wall to "
                    "climb."))

    # Which blocker dominates across the most firms?
    blocker_counts = Counter(dominant_by_firm.values())
    dom_key, dom_count = blocker_counts.most_common(1)[0]
    dom_label = BREACH_LABELS.get(dom_key, dom_key)
    dom_firms = [name for name, k in dominant_by_firm.items() if k == dom_key]

    # Contradiction: do different firms imply opposite directions?
    directions = {}
    for name, k in dominant_by_firm.items():
        directions[name] = _direction(k)
    aggression_firms = [n for n, d in directions.items() if d == "need_more_aggression"]
    caution_firms = [n for n, d in directions.items() if d == "need_more_caution"]
    contradiction = bool(aggression_firms) and bool(caution_firms)

    # --- Headlines ----------------------------------------------------------
    if dom_count >= 2 and dom_count >= len(dominant_by_firm) * 0.5:
        headline = (f"Single leverage point: '{dom_label}' is the dominant blocker "
                    f"at {dom_count} of {len(dominant_by_firm)} firms that challenge "
                    f"you. Address that one thing and the most doors open at once.")
    else:
        headline = (f"No single dominant blocker - different firms stop you for "
                    f"different reasons, so there's no one quick fix across all of "
                    f"them.")

    if contradiction:
        detail = (
            f"You face OPPOSITE problems at different firms. At "
            f"{len(caution_firms)} firm(s) you breach a risk limit "
            f"({', '.join(_short(n) for n in caution_firms[:3])}"
            f"{'...' if len(caution_firms) > 3 else ''}) - there you'd need to be "
            f"MORE cautious. At {len(aggression_firms)} firm(s) you simply don't "
            f"reach the target in time "
            f"({', '.join(_short(n) for n in aggression_firms[:3])}"
            f"{'...' if len(aggression_firms) > 3 else ''}) - there you'd need to be "
            f"MORE aggressive. The same change can't fix both groups; this is why a "
            f"single 'be more careful' or 'push harder' instinct misfires across "
            f"firms. Pick the group you're actually targeting first.")
    else:
        only_dir = "reach the profit target faster" if aggression_firms else \
                   "respect the risk limits more tightly"
        detail = (f"The firms that block you mostly point the same way: you'd need "
                  f"to {only_dir}. There's no cross-firm contradiction, so one "
                  f"coherent adjustment direction applies. The leverage point above "
                  f"is where to start.")

    return LeverageMap(
        dominant_blocker_key=dom_key,
        dominant_blocker_label=dom_label,
        firms_blocked_by_dominant=dom_count,
        total_firms=len(dominant_by_firm),
        dominant_firm_names=[_short(n) for n in dom_firms],
        contradiction=contradiction,
        aggression_firms=[_short(n) for n in aggression_firms],
        caution_firms=[_short(n) for n in caution_firms],
        headline=headline,
        detail=detail,
    )


def _short(firm_label: str) -> str:
    """'Apex - EOD 50K Evaluation (Futures)' -> 'Apex'."""
    return firm_label.split(" - ")[0].strip()
