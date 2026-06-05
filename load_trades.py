"""
load_trades.py
--------------
Parses a broker CSV into a list of daily net P/L values.

Supported (V1):
  - MT4 / MT5 history exports (looks for profit + close-time columns)
  - Generic CSV with a 'profit'/'pnl' column and optional date column

Design choices:
  - We do NOT persist the file. Parsing happens in memory.
  - Account number / name-like columns are dropped before anything else.
  - If we cannot parse it, we say so plainly instead of guessing.
"""

from __future__ import annotations
import io
import pandas as pd

PROFIT_COLS = ["profit", "pnl", "p/l", "net", "netprofit", "net_profit", "result"]
DATE_COLS = ["close time", "close_time", "closetime", "date", "time", "closed",
             "close date", "open time"]
SENSITIVE_COLS = ["account", "account_number", "accountnumber", "login", "name",
                  "client", "email", "phone"]


class TradeParseError(Exception):
    """Raised when a file cannot be parsed. Message is user-safe."""


def _find_col(columns, candidates):
    low = {c.lower().strip(): c for c in columns}
    for cand in candidates:
        if cand in low:
            return low[cand]
    # loose contains-match
    for cand in candidates:
        for lc, orig in low.items():
            if cand in lc:
                return orig
    return None


def load_trades_csv(file_or_bytes) -> tuple[list[float], dict]:
    """
    Returns (daily_pnls, meta).
    meta = {n_trades, n_days, profitable_days, source_hint, warnings:[...]}
    Raises TradeParseError with a friendly message if unparseable.
    """
    warnings: list[str] = []
    try:
        if isinstance(file_or_bytes, (bytes, bytearray)):
            df = pd.read_csv(io.BytesIO(file_or_bytes))
        else:
            df = pd.read_csv(file_or_bytes)
    except Exception:
        raise TradeParseError(
            "We could not parse this file. Export a standard CSV from your "
            "platform (MT4/MT5 history or a generic CSV) and try again — or "
            "send it for manual review.")

    # privacy first: drop anything that looks identifying
    drop = [c for c in df.columns if any(s in c.lower() for s in SENSITIVE_COLS)]
    if drop:
        df = df.drop(columns=drop)
        warnings.append(f"Masked {len(drop)} identifying column(s) before processing.")

    profit_col = _find_col(df.columns, PROFIT_COLS)
    if profit_col is None:
        raise TradeParseError(
            "We could not find a profit/P&L column in this file. Make sure your "
            "export includes a per-trade profit column, or send it for manual review.")

    df[profit_col] = pd.to_numeric(df[profit_col], errors="coerce")
    df = df.dropna(subset=[profit_col])
    if len(df) == 0:
        raise TradeParseError("No numeric trade results were found in this file.")

    date_col = _find_col(df.columns, DATE_COLS)
    source_hint = "generic CSV"
    if date_col is not None:
        parsed = pd.to_datetime(df[date_col], errors="coerce")
        if parsed.notna().sum() >= max(2, int(0.5 * len(df))):
            df["_day"] = parsed.dt.date
            daily = df.groupby("_day")[profit_col].sum()
            gaps = parsed.isna().sum()
            if gaps:
                warnings.append(f"{gaps} row(s) had unreadable dates and were grouped loosely.")
            daily_pnls = [float(x) for x in daily.tolist()]
            source_hint = "MT4/MT5 or dated CSV"
            n_days = len(daily_pnls)
        else:
            daily_pnls = [float(x) for x in df[profit_col].tolist()]
            n_days = len(daily_pnls)
            warnings.append("Dates were unreadable — treated each trade as its own day.")
    else:
        daily_pnls = [float(x) for x in df[profit_col].tolist()]
        n_days = len(daily_pnls)
        warnings.append("No date column found — treated each trade as its own day.")

    if n_days < 10:
        warnings.append(
            "Fewer than 10 trading days of data — the estimate will be rough. "
            "More history means a sharper result.")

    meta = {
        "n_trades": int(len(df)),
        "n_days": int(n_days),
        "profitable_days": int(sum(1 for p in daily_pnls if p > 0)),
        "source_hint": source_hint,
        "warnings": warnings,
    }
    return daily_pnls, meta
