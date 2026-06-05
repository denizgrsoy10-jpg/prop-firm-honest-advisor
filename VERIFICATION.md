# Ruleset verification checklist

**Do NOT enable real (live) payments while any firm below is `needs_verified`.**
Every ruleset in `firms/` is currently **seed data**. Before charging anyone,
open each firm's official site, confirm every field, then set
`verification_status: "verified"` and update `last_verified_date` in the JSON.

For each firm, verify these fields against the official site:

- account_size, currency
- phases / profit_target_pct (per phase)
- daily_loss_limit_pct (and what it's measured against: balance vs equity, prev close vs initial)
- max_drawdown_pct **and** drawdown_type (static | trailing_eod | trailing_intraday)
- min_trading_days, min_profitable_days
- consistency_rule_pct (best-day / consistency cap)
- news_rule (allowed | restricted | not_allowed) + region restrictions
- fee (and the exact account tier the fee maps to)

## Status

| Firm / product | Source to check | Verified? | Date | By |
|---|---|---|---|---|
| FTMO — 2-Step Challenge | ftmo.com / ftmo.oanda.com | ✅ verified | 2026-06-05 | Candor |
| FTMO — 1-Step Challenge | ftmo.com / ftmo.oanda.com | ✅ verified | 2026-06-05 | Candor |
| FundedNext — Stellar 2-Step | fundednext.com | ☐ needs_verified | — | — |
| The5ers — New High Stakes | the5ers.com | ☐ needs_verified | — | — |
| E8 Markets — E8 One | e8markets.com | ☐ needs_verified | — | — |
| Apex — EOD 50K (Futures) | apextraderfunding.com | ☐ needs_verified | — | — |

## Known approximations to resolve or keep disclosed
- Trailing/intraday drawdown is estimated from end-of-day balances (no intraday data).
- Apex futures **$** thresholds are approximated as a **%** of account size — confirm exact $ figures.
- Daily-loss basis (balance vs equity, which reference point) varies by firm — confirm each.

## Rule
Flip `verification_status` to `verified` in the JSON only after a real person has
checked the firm's live rules. The brand is "honest" — shipping unverified
numbers as if certain breaks it on day one.
