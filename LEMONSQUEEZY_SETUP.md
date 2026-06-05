# LemonSqueezy setup — Candor RealityCheck

Decision locked: **LemonSqueezy** (merchant of record — handles global VAT/sales tax;
supports payouts to Türkiye). Start as a sole proprietorship; talk to an accountant
after the first ~10 sales. (Not legal/tax advice — confirm for your situation.)

## 1. Product listing description (use this — it keeps approval clean)

> **Candor RealityCheck** is a statistical simulation tool for traders. Users upload
> their trade history, and the app compares it against verified prop firm rules to
> generate a probability report and downloadable PDF. It does **not** provide financial
> advice, trading signals, or any guaranteed outcome. Digital report delivered instantly.

Avoid these words in the listing: *investment advice, trading signals, guaranteed pass,
financial consulting.* They trigger review problems.

## 2. Products to create (one-time, digital)

| Product | Price |
|---|---|
| Full Report | $19 |
| Rerun | $9 |
| Bundle · 3 Reports | $49 |

## 3. What to collect from LemonSqueezy (you do this — I can't)

1. **API key** — Settings → API → create key
2. **Store ID** — shown for your store
3. **Variant ID** for each product (Full Report at minimum)

## 4. Where the keys go — Streamlit "Secrets" (NOT in the repo)

In Streamlit Cloud → your app → **Settings → Secrets**, paste:

```
PAYMENT_MODE = "live"
PAYMENT_PROVIDER = "lemonsqueezy"
LEMONSQUEEZY_API_KEY = "..."
LEMONSQUEEZY_STORE_ID = "..."
LEMONSQUEEZY_VARIANT_FULL = "..."
LEMONSQUEEZY_VARIANT_RERUN = "..."     # optional
LEMONSQUEEZY_VARIANT_BUNDLE = "..."    # optional
```

The moment `PAYMENT_MODE="live"` is set with a valid key, the demo/test banner
disappears automatically and the $19 is charged for real.

## 5. Flow (what the user experiences)

free preview → "Unlock Full Report — $19" → LemonSqueezy checkout (card) →
payment success → back to app → full report + PDF unlock.
The customer pays LemonSqueezy by card; you never receive an IBAN transfer from them.
LemonSqueezy takes its fee (~5% + $0.50, plus small intl/PayPal adders) and pays the
net to your linked bank/PayPal as a periodic payout in USD.

## 6. What I (the code) will do once you have the keys

Fill in the LemonSqueezy adapter in `payments.py`:
- `create_checkout()` → create a LemonSqueezy checkout for the variant, return its URL
- `verify_payment()` → confirm the order is paid before unlocking

No key is ever written into the repo — everything is read from the Secrets above at runtime.
