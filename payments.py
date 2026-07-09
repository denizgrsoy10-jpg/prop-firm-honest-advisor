"""
payments.py
-----------
Payment adapter for Candor RealityCheck.

  PAYMENT_MODE=mock  (default)  -> instant local success, no network, no keys.
                                   Lets the whole funnel be tested locally.
  PAYMENT_MODE=live             -> returns real LemonSqueezy checkout URLs.

NO API KEY IS STORED IN THIS REPO.
"""

from __future__ import annotations
import os
import uuid

# ── Product catalogue ────────────────────────────────────────────────────────

PRODUCTS = {
    "full_report": {
        "name": "Candor RealityCheck — Full Report",
        "amount": 900,       # $9.00
        "currency": "usd",
        "checkout_url": (
            "https://candorrealitycheck.lemonsqueezy.com"
            "/checkout/buy/a7327162-1176-4f60-b312-e0599b66bf6c"
        ),
    },
    "bundle3": {
        "name": "Candor RealityCheck — 3-Report Bundle",
        "amount": 1900,      # $19.00
        "currency": "usd",
        "checkout_url": (
            "https://candorrealitycheck.lemonsqueezy.com"
            "/checkout/buy/6c39422c-98a6-4209-9c21-4b98e2a3c398"
        ),
    },
}


def mode() -> str:
    return os.environ.get("PAYMENT_MODE", "mock").lower()


class PaymentError(Exception):
    pass


# ── Public API ───────────────────────────────────────────────────────────────

def create_checkout(product_key: str, report_id: str = "", **_kw) -> dict:
    """
    Returns {checkout_url, session_id}.

    In mock mode the checkout_url is a local sentinel the app can
    resolve immediately (for local testing).

    In live mode it returns the real LemonSqueezy hosted checkout URL.
    The post-payment return to the app is handled by LemonSqueezy's
    per-product "Confirmation modal" button (set in the dashboard), which
    sends the buyer to ...streamlit.app/?paid=1 after payment.
    """
    if product_key not in PRODUCTS:
        raise PaymentError(f"Unknown product: {product_key}")

    if mode() == "mock":
        return {
            "checkout_url": "MOCK_CHECKOUT",
            "session_id": f"mock_{uuid.uuid4().hex[:12]}",
        }

    # ── Live mode: return the real LemonSqueezy hosted checkout URL ──
    return {
        "checkout_url": PRODUCTS[product_key]["checkout_url"],
        "session_id": f"ls_{uuid.uuid4().hex[:12]}",
    }


def verify_payment(session_id: str) -> bool:
    """
    True if the session is paid.
    Mock sessions are always paid.
    Live verification requires LemonSqueezy webhook or API check.
    """
    if session_id.startswith("mock_"):
        return True

    # For MVP: trust the redirect. The user lands on success_url only
    # after LemonSqueezy confirms payment. For production hardening,
    # add webhook signature verification or API order lookup here.
    #
    # TODO: implement LemonSqueezy webhook verification
    #   POST /webhooks/lemonsqueezy  -> verify X-Signature header
    #   -> mark order as paid in DB
    return True


def get_checkout_url(product_key: str) -> str:
    """
    Convenience helper: returns the direct checkout URL for a product.
    Use this from Streamlit buttons / st.link_button().
    """
    if product_key not in PRODUCTS:
        raise PaymentError(f"Unknown product: {product_key}")

    if mode() == "mock":
        return "MOCK_CHECKOUT"

    import urllib.parse
    base = PRODUCTS[product_key]["checkout_url"]
    app_base = "https://prop-firm-honest-advisor-i3qugmvz9vnb7jw2im4vny.streamlit.app"
    redirect = f"{app_base}/?mode=prop_firm&paid=1"
    return base + "?" + urllib.parse.urlencode({
        "checkout[custom][redirect_url]": redirect,
    })


def get_price_display(product_key: str) -> str:
    """Returns a human-readable price string like '$9'."""
    if product_key not in PRODUCTS:
        return "?"
    return f"${PRODUCTS[product_key]['amount'] // 100}"
