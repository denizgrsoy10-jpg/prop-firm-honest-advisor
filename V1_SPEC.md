# V1_SPEC — Prop Firm RealityCheck (Candor)

The first paying product. Goal of V1: **a working funnel that takes money**, not
a perfect engine. Bigger vision (Signal Scanner, Risk DNA, Solo Asset Check,
Decision Firewall) stays parked as "coming soon" — do not build it yet.

## Funnel (must work end to end)

1. CSV upload screen
2. CSV parser / validation (`load_trades.py`)
3. Free preview result
4. Locked full report section (blurred until paid)
5. Payment placeholder / provider adapter (`payments.py`)
6. Unlock on payment success
7. PDF export (`pdf_export.py`)
8. Rerun ($9) and Bundle ($49) CTAs
9. This spec committed to the repo

## Free preview shows
- best matching firm
- worst (toughest) matching firm
- estimated pass-odds range
- killer rule
- go / wait / skip verdict
- "unlock full report" CTA

## Paid full report shows
- all firms comparison
- killer rule per firm
- expected fee burn per firm
- what-if simulator
- daily violation / breakdown summary
- equity curve
- downloadable PDF

## What-if simulator (V1)
- Risk presets: **100% / 80% / 65% / 50%**.
- Each preset re-runs the simulation on risk-scaled daily P/L.
- It is an **approximation** and must be labelled:
  > *Estimated what-if scenario — based on scaling your historical daily risk.
  > A first-order approximation, not a guarantee.*
- Never present false precision.

## Payment
- API keys are **never** committed. Read from env at runtime.
- `PAYMENT_MODE=mock` → local testing works with no keys.
- `PAYMENT_MODE=live` → provider adapter (`stripe` | `lemonsqueezy` | `paddle`).
- `payments.py` is provider-agnostic so the choice can change later.

## PDF
Title, generated date, uploaded-file summary, pass odds, killer rules, firm
comparison, what-if table, expected fee burn, and a clear *not financial advice*
note.

## Rulesets (`firms/*.json`)
Fields: `firm_name, product, account_size, profit_target (phases),
daily_loss_limit_pct, max_drawdown_pct, trailing_drawdown (drawdown_type),
min_trading_days, min_profitable_days, consistency_rule_pct, news_rule, fee,
last_verified_date, source_note, verification_status`.
- Unknown/uncertain rules are seed data → `verification_status:
  "needs_verification"` + `source_note`. **Never present uncertain data as
  certain** — it would break the honesty brand.

## Module architecture
`simulator.py · rules_engine.py · what_if.py · report_builder.py ·
pdf_export.py · payments.py · analytics.py · load_trades.py · app.py`
Keep it clean so the engine can grow without a rewrite.

## Analytics events
`upload_started · parse_success · parse_failed · preview_viewed ·
unlock_clicked · payment_success · full_report_viewed · pdf_downloaded ·
rerun_clicked` (no PII).

## Privacy
- CSV is **not** persisted (in-memory parse).
- Account-number / name-like columns are masked before processing.
- Report screen states: *your data is used only for this simulation*.

## Acceptance criteria
- [x] User can see a preview from the demo CSV.
- [x] Mock payment unlocks the full report.
- [x] PDF downloads.
- [x] What-if table renders.
- [x] Rerun and Bundle CTAs visible.
- [x] Locked sections are blurred/locked before payment.
- [x] README documents local run steps.

## Next (after this)
1. Deploy (GitHub → Streamlit Cloud), keep `PAYMENT_MODE=mock` until provider wired.
2. Wire a real payment provider (Stripe/LemonSqueezy/Paddle) via env keys.
3. Verify each firm ruleset against the firm's site; flip `verification_status`.
4. Traffic: SEO mini-tools + affiliate. Then Signal Scanner (viral), Risk DNA (subscription).
