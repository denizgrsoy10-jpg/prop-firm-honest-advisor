"""
report_cache.py
---------------
Temporary server-side cache for the payment-return flow.

Problem: user uploads CSV -> gets preview -> pays on LemonSqueezy -> returns
to Streamlit.  But Streamlit's session_state is wiped on a full page
navigation, so the CSV, preview, and all computed data are gone.

Solution: before redirecting to checkout, serialise the essential state to
a file keyed by report_id.  When the user returns with ?paid=1&rid=X,
load it back and continue as if nothing happened.

We use pickle (not JSON) because the cached state contains numpy arrays,
pandas objects, and datetimes that are not JSON-serialisable.

Storage: /tmp/candor_cache/ -- survives across Streamlit reruns on the same
dyno but NOT across deploys.  This is fine: the gap between "pay" and
"return" is typically < 5 minutes.  If the file is missing, we show a
friendly "please re-upload" message instead of crashing.
"""

from __future__ import annotations
import os, time, pickle

CACHE_DIR = "/tmp/candor_cache"
MAX_AGE_SECONDS = 3600  # 1 hour -- plenty for a checkout round-trip


def _ensure_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def save(report_id: str, data: dict) -> str:
    """Persist state to disk with pickle.  Returns report_id for convenience."""
    _ensure_dir()
    path = os.path.join(CACHE_DIR, f"{report_id}.pkl")
    with open(path, "wb") as f:
        pickle.dump(data, f)
    return report_id


def load(report_id: str) -> dict | None:
    """Load cached state, or None if missing / expired / corrupt."""
    path = os.path.join(CACHE_DIR, f"{report_id}.pkl")
    if not os.path.exists(path):
        return None
    # Expire old files
    if time.time() - os.path.getmtime(path) > MAX_AGE_SECONDS:
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def cleanup():
    """Remove expired cache files (call occasionally)."""
    _ensure_dir()
    now = time.time()
    for fname in os.listdir(CACHE_DIR):
        fpath = os.path.join(CACHE_DIR, fname)
        try:
            if now - os.path.getmtime(fpath) > MAX_AGE_SECONDS:
                os.remove(fpath)
        except OSError:
            pass


def make_rid() -> str:
    """Generate a short unique report-id for caching."""
    import uuid
    return f"CND-{uuid.uuid4().hex[:8]}"
