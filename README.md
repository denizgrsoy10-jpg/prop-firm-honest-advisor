# Prop Firm RealityCheck — Candor (V1)

Upload your real trading history, get honest pass odds for each prop firm
challenge, the rule most likely to eliminate you, expected fee burn, and a
what-if simulator. Free preview, paid ($19) full report with PDF.

> Statistical simulation only. **Not** financial, investment, or trading advice.
> No outcome with any firm is guaranteed.

## Run locally

```bash
pip install -r requirements.txt
PAYMENT_MODE=mock streamlit run app.py
```

Then: upload a CSV (or click **Use demo data**) → see the free preview →
**Unlock full report** (mock payment succeeds instantly) → view the full report,
what-if table, equity curve, and **Download PDF**.

## Payment

No API keys are stored in this repo. Payments are driven by environment vars:

```bash
PAYMENT_MODE=mock                 # default: instant local success, no keys
PAYMENT_MODE=live                 # use a real provider adapter
PAYMENT_PROVIDER=stripe           # stripe | lemonsqueezy | paddle
STRIPE_SECRET_KEY=sk_live_...     # read from env at runtime, never committed
```

The live adapters in `payments.py` are thin stubs — wire in the real SDK calls
in your deployment, where the keys live.

## Architecture

| File | Responsibility |
|---|---|
| `app.py` | Streamlit funnel (upload → preview → paywall → report → PDF) |
| `load_trades.py` | CSV parse/validate (MT4/MT5/generic), masking |
| `rules_engine.py` | Firm rulesets + single-phase rule evaluation |
| `simulator.py` | Monte Carlo bootstrap, pass odds, killer rule |
| `what_if.py` | Risk-scaling what-if (clearly labelled as estimate) |
| `report_builder.py` | Builds free preview + paid full report payloads |
| `pdf_export.py` | Renders the full report to PDF (reportlab) |
| `payments.py` | Provider-agnostic adapter (mock/live, ENV keys) |
| `analytics.py` | Local event log (allowed events only, no PII) |
| `firms/*.json` | Per-firm rulesets (seed data; verify before relying) |
| `data/demo_trades.csv` | Demo file so the funnel works out of the box |

## Honesty notes (by design)

- Rulesets are **seed data** marked `needs_verification`. Verify on each firm's
  site before treating numbers as exact. Rules change.
- We only have daily net P/L, so **trailing/intraday drawdown is approximated**
  from end-of-day balances. This is disclosed in-app and in the PDF.
- Futures $ thresholds (e.g. Apex) are approximated as a % of account.
- What-if results are first-order **estimates**, never guarantees.
