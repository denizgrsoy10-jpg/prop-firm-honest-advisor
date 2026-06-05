"""
payments.py
-----------
A provider-agnostic payment adapter.

  PAYMENT_MODE=mock  (default)  -> instant local success, no network, no keys.
                                   Lets the whole funnel be tested locally.
  PAYMENT_MODE=live             -> dispatches to a real provider adapter
                                   (Stripe / LemonSqueezy / Paddle) using keys
                                   read ONLY from environment variables.

NO API KEY IS EVER STORED IN THIS REPO. Live adapters read os.environ at run
time. The live adapters here are intentionally thin stubs: wire in the real SDK
calls in your own deployment, where the keys live.
"""

from __future__ import annotations
import os
import uuid

PRODUCTS = {
    "full_report": {"name": "Full report", "amount": 1900, "currency": "usd"},
    "rerun":       {"name": "Rerun",       "amount": 900,  "currency": "usd"},
    "bundle3":     {"name": "Bundle · 3 reports", "amount": 4900, "currency": "usd"},
}


def mode() -> str:
    return os.environ.get("PAYMENT_MODE", "mock").lower()


def provider() -> str:
    return os.environ.get("PAYMENT_PROVIDER", "stripe").lower()


class PaymentError(Exception):
    pass


def create_checkout(product_key: str, success_url: str, cancel_url: str) -> dict:
    """
    Returns {checkout_url, session_id}. In mock mode the checkout_url is a local
    sentinel the app can resolve immediately.
    """
    if product_key not in PRODUCTS:
        raise PaymentError(f"Unknown product: {product_key}")

    if mode() == "mock":
        return {"checkout_url": "MOCK_CHECKOUT", "session_id": f"mock_{uuid.uuid4().hex[:12]}"}

    p = provider()
    if p == "stripe":
        return _stripe_checkout(product_key, success_url, cancel_url)
    if p in ("lemonsqueezy", "lemon"):
        return _lemonsqueezy_checkout(product_key, success_url, cancel_url)
    if p == "paddle":
        return _paddle_checkout(product_key, success_url, cancel_url)
    raise PaymentError(f"Unsupported provider: {p}")


def verify_payment(session_id: str) -> bool:
    """True if the session is paid. Mock sessions are always paid."""
    if mode() == "mock" or session_id.startswith("mock_"):
        return True
    p = provider()
    if p == "stripe":
        return _stripe_verify(session_id)
    if p in ("lemonsqueezy", "lemon"):
        return _lemonsqueezy_verify(session_id)
    if p == "paddle":
        return _paddle_verify(session_id)
    raise PaymentError(f"Unsupported provider: {p}")


# --- live provider stubs (wire real SDK calls in your deployment) -------------

def _stripe_checkout(product_key, success_url, cancel_url):
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise PaymentError("STRIPE_SECRET_KEY not set in environment.")
    # import stripe; stripe.api_key = key
    # session = stripe.checkout.Session.create(...)
    # return {"checkout_url": session.url, "session_id": session.id}
    raise NotImplementedError("Wire Stripe SDK here, using STRIPE_SECRET_KEY from env.")


def _stripe_verify(session_id):
    raise NotImplementedError("Wire stripe.checkout.Session.retrieve(session_id) here.")


def _lemonsqueezy_checkout(product_key, success_url, cancel_url):
    if not os.environ.get("LEMONSQUEEZY_API_KEY"):
        raise PaymentError("LEMONSQUEEZY_API_KEY not set in environment.")
    raise NotImplementedError("Wire LemonSqueezy checkout API here.")


def _lemonsqueezy_verify(session_id):
    raise NotImplementedError("Wire LemonSqueezy order verification here.")


def _paddle_checkout(product_key, success_url, cancel_url):
    if not os.environ.get("PADDLE_API_KEY"):
        raise PaymentError("PADDLE_API_KEY not set in environment.")
    raise NotImplementedError("Wire Paddle transaction API here.")


def _paddle_verify(session_id):
    raise NotImplementedError("Wire Paddle transaction verification here.")
