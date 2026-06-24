"""
rules_engine.py
---------------
Loads firm rulesets (JSON) and evaluates a single equity path (a sequence of
daily P/L values) against one challenge phase's rules.

Honesty notes (these are surfaced to the user, never hidden):
- We only have daily net P/L, not tick data. "Intraday" drawdown is therefore
  approximated from end-of-day balances. This is flagged wherever it matters.
- Futures $ thresholds (e.g. Apex) are approximated as a % of account size.
- Rulesets marked verification_status="needs_verification" are seed data.
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from typing import Optional

FIRMS_DIR = os.path.join(os.path.dirname(__file__), "firms")

# Human-readable labels for each breach reason (the "killer rule").
BREACH_LABELS = {
    "daily_loss_limit": "Daily loss limit",
    "max_drawdown": "Maximum drawdown",
    "trailing_drawdown": "Trailing drawdown",
    "consistency_rule": "Consistency / best-day rule",
    "min_trading_days": "Minimum trading days not met",
    "min_profitable_days": "Minimum profitable days not met",
    "target_not_reached": "Profit target not reached in window",
}


def load_firms(firms_dir: str | None = None) -> list[dict]:
    """
    Load every firm ruleset, whether they live in a firms/ subfolder OR sit flat
    in the repo root (GitHub's web upload sometimes flattens folders). We only
    accept JSON files that actually look like a ruleset (have firm_name + phases),
    so other JSON in the repo is ignored. Deduped by id, firms/ wins.
    """
    base = os.path.dirname(os.path.abspath(__file__))
    search_dirs = []
    if firms_dir:
        search_dirs.append(firms_dir)
    search_dirs += [os.path.join(base, "firms"), base]

    firms: dict[str, dict] = {}
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, name), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                continue
            if isinstance(data, dict) and "firm_name" in data and "phases" in data:
                key = data.get("id", name)
                if key not in firms:   # first hit wins -> firms/ before root
                    firms[key] = data
    return list(firms.values())


def available_account_sizes(firms: list[dict]) -> list[int]:
    """Union of all account sizes offered across the given firms, sorted."""
    sizes = set()
    for f in firms:
        for t in (f.get("size_tiers") or []):
            sizes.add(int(t["size"]))
        sizes.add(int(f.get("account_size", 0)))
    sizes.discard(0)
    return sorted(sizes)


def apply_account_size(firm: dict, size: int) -> dict:
    """Return a shallow copy of `firm` rebased to `size`.

    PRESENTATION/PARAMETER ONLY — the engine math is percentage-based, so pass
    odds are identical across sizes. We only swap account_size and fee so the
    dollar targets, equity curve, and fee-burn reflect the size the user picked.
    If the firm doesn't offer that exact size, we return it unchanged.
    """
    tiers = firm.get("size_tiers") or []
    match = next((t for t in tiers if int(t["size"]) == int(size)), None)
    if not match:
        return firm  # size not offered by this firm -> leave as-is
    out = dict(firm)
    out["_size_base"] = int(firm.get("account_size"))  # original, for P/L scaling
    out["account_size"] = int(match["size"])
    if match.get("fee") is not None:
        out["fee"] = match["fee"]
    out["_selected_size"] = int(match["size"])
    out["_fee_estimated"] = not firm.get("size_tiers_verified", False)
    return out


@dataclass
class PhaseResult:
    passed: bool
    breach_reason: Optional[str] = None
    days_used: int = 0
    final_balance: float = 0.0
    equity_curve: list[float] = field(default_factory=list)


def evaluate_phase(daily_pnls: list[float], firm: dict, phase_index: int) -> PhaseResult:
    """
    Walk one phase day-by-day and return whether it passes and, if not, the
    FIRST rule that broke it (that rule is the 'killer rule' for this path).
    """
    start = float(firm["account_size"])
    phase = firm["phases"][phase_index]
    target_balance = start * (1.0 + phase["target_pct"] / 100.0)

    dd_pct = firm.get("max_drawdown_pct")
    dd_type = firm.get("drawdown_type", "static")
    daily_limit_pct = firm.get("daily_loss_limit_pct")
    consistency_pct = firm.get("consistency_rule_pct")
    min_days = firm.get("min_trading_days", 0) or 0
    min_profit_days = firm.get("min_profitable_days", 0) or 0

    daily_limit_amt = (daily_limit_pct / 100.0 * start) if daily_limit_pct else None
    dd_amt = (dd_pct / 100.0 * start) if dd_pct else None

    balance = start
    peak = start
    curve = [start]
    profitable_days = 0
    day_profits = []  # for consistency rule

    for i, pnl in enumerate(daily_pnls, start=1):
        # 1) daily loss limit (checked on the day's net loss)
        if daily_limit_amt is not None and pnl < 0 and abs(pnl) > daily_limit_amt:
            return PhaseResult(False, "daily_loss_limit", i, balance, curve)

        balance += pnl
        curve.append(balance)
        if pnl > 0:
            profitable_days += 1
        day_profits.append(pnl)
        peak = max(peak, balance)

        # 2) drawdown
        if dd_amt is not None:
            if dd_type == "static":
                floor = start - dd_amt
            else:  # trailing_eod or trailing_intraday (intraday approximated from EOD)
                floor = peak - dd_amt
            if balance < floor:
                reason = "max_drawdown" if dd_type == "static" else "trailing_drawdown"
                return PhaseResult(False, reason, i, balance, curve)

        # 3) target reached? (only counts once minimums are satisfiable)
        if balance >= target_balance and i >= min_days:
            if profitable_days < min_profit_days:
                continue  # hit target but not enough profitable days yet
            # consistency: no single day may exceed X% of total profit
            if consistency_pct is not None:
                total_profit = balance - start
                if total_profit > 0:
                    biggest = max(day_profits)
                    if biggest > (consistency_pct / 100.0) * total_profit:
                        return PhaseResult(False, "consistency_rule", i, balance, curve)
            return PhaseResult(True, None, i, balance, curve)

    # window exhausted without hitting target
    if balance < target_balance:
        return PhaseResult(False, "target_not_reached", len(daily_pnls), balance, curve)
    if len(daily_pnls) < min_days:
        return PhaseResult(False, "min_trading_days", len(daily_pnls), balance, curve)
    return PhaseResult(False, "target_not_reached", len(daily_pnls), balance, curve)


def ruleset_version(firms: list[dict]) -> str:
    """A simple version stamp = the latest verification date across loaded firms."""
    dates = [f.get("last_verified_date") for f in firms if f.get("last_verified_date")]
    return f"RULESET-{max(dates)}" if dates else "RULESET-unversioned"
