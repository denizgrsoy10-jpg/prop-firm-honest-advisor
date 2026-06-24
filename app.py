"""
app.py — Prop Firm RealityCheck (Candor)
========================================
The money-taking V1 funnel:

  upload CSV -> parse/validate -> FREE preview -> locked full report
  -> (mock or live) payment -> unlock -> full report + PDF -> rerun/bundle CTAs

Run locally:
    pip install -r requirements.txt
    PAYMENT_MODE=mock streamlit run app.py
"""

from __future__ import annotations
import os
import streamlit as st

from rules_engine import load_firms, available_account_sizes, apply_account_size
from load_trades import load_trades_csv, TradeParseError
from report_builder import build_preview, build_full_report
from pdf_export import build_pdf, build_own_account_pdf
import payments
import analytics
import tracking
import own_account

# --- branding assets (robust: never crash if a file is missing) --------------
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
def _asset(name):
    p = os.path.join(ASSETS_DIR, name)
    return p if os.path.exists(p) else None

st.set_page_config(page_title="Candor RealityCheck",
                   page_icon=_asset("candor-favicon-32.png") or "🔦",
                   layout="centered")

# --- routing to extra surfaces (?page=outcome|honesty-ledger|admin|signal) ----
import views
_qp = st.query_params
_page = _qp.get("page")
if _page in ("outcome", "ledger", "honesty-ledger", "admin", "signal", "autopilot"):
    if _page == "outcome":
        views.render_outcome(_qp.get("report_id", ""))
    elif _page in ("ledger", "honesty-ledger"):
        views.render_ledger()
    elif _page == "admin":
        views.render_admin()
    elif _page == "signal":
        views.render_signal()
    elif _page == "autopilot":
        views.render_autopilot()
    st.stop()

# --- session state -----------------------------------------------------------
ss = st.session_state

# Landing'den gelen ?mode=own_account / ?mode=prop_firm linkleri:
# kullanıcı modu sayfa açılınca seçsin diye, radio'yu manuel oynatmasına gerek kalmasın.
_qp_mode = _qp.get("mode")
if _qp_mode in ("own", "own_account"):
    ss["mode"] = "own_account"
elif _qp_mode in ("prop", "prop_firm"):
    ss["mode"] = "prop_firm"
ss.setdefault("daily_pnls", None)
ss.setdefault("meta", None)
ss.setdefault("preview", None)
ss.setdefault("unlocked", False)
ss.setdefault("checkout", None)
ss.setdefault("market_label", None)
ss.setdefault("account_size", None)
ss.setdefault("preview_market", None)
ss.setdefault("report_id", None)
ss.setdefault("logged", False)
ss.setdefault("used_demo", False)
ss.setdefault("oa_preview", None)
ss.setdefault("mode", "prop_firm")


def _reset():
    for k in ("daily_pnls", "meta", "preview", "checkout", "market_label",
              "preview_market", "report_id", "oa_preview", "account_size"):
        ss[k] = None
    ss["unlocked"] = False
    ss["logged"] = False
    ss["legal_logged_upload"] = False
    ss["legal_logged_payment"] = False


def _demo_path():
    """Find the demo CSV whether it's in data/ or sitting flat in the repo root."""
    base = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(base, "data", "demo_trades.csv"),
              os.path.join(base, "demo_trades.csv")):
        if os.path.exists(p):
            return p
    return None
# ============================================================================
# Own Account RealityCheck — full mode flow
# ============================================================================
def _render_own_account():
    """Render the Own Account RealityCheck flow.

    Mirrors the Prop Firm funnel structurally:
      account inputs -> upload (with consent) -> free preview ->
      locked full report -> (mock/live) payment -> full report + PDF

    But scoring is band-only (no sharp probabilities), and every output is
    framed as statistical risk diagnostics, not advice.
    """
    UPLOAD_CONSENT_TEXT = ("I understand this report is a statistical "
                           "simulation and risk-diagnostics report, not "
                           "financial, investment, or trading advice.")
    PAY_CONSENT_TEXT = ("Digital report. Statistical simulation only. "
                        "No guaranteed outcome. Sales are generally final "
                        "after report generation.")

    # --- 1) account inputs ---------------------------------------------------
    st.subheader("1 · Your account")
    c1, c2, c3 = st.columns(3)
    start_balance = c1.number_input("Starting balance (USD)",
                                    min_value=100.0, value=10000.0, step=500.0)
    leverage = c2.number_input("Leverage (e.g. 30 for 1:30)",
                               min_value=1.0, value=30.0, step=1.0)
    stop_out_pct = c3.number_input("Broker stop-out % (optional)",
                                   min_value=10.0, max_value=100.0,
                                   value=50.0, step=5.0)
    st.caption("Used only for margin-pressure context. Estimated from "
               "uploaded history; not a forecast.")

    # --- 2) upload (with consent) -------------------------------------------
    st.subheader("2 · Upload your trade history")
    st.write("Same CSV format as Prop Firm mode. **MT4 / MT5 history export** "
             "or **generic CSV** with a profit column. Your file is used "
             "only for this simulation and is not stored.")

    _consent_upload = st.checkbox(UPLOAD_CONSENT_TEXT, key="oa_consent_upload")
    if not _consent_upload:
        st.caption("Tick the box above to enable the upload.")

    up = st.file_uploader("Trade history (.csv)", type=["csv"],
                          key="oa_uploader",
                          disabled=not _consent_upload)
    col_a, col_b = st.columns([1, 1])
    use_demo = col_b.button("Use demo data", key="oa_demo",
                            disabled=not _consent_upload)

    if (up is not None or use_demo) and ss.daily_pnls is None and _consent_upload:
        analytics.log_event("oa_upload_started", {"demo": bool(use_demo)})
        if not ss.get("legal_logged_upload"):
            tracking.log_legal_acceptance(
                source="upload", consent_text=UPLOAD_CONSENT_TEXT)
            ss["legal_logged_upload"] = True
        try:
            if use_demo:
                dp = _demo_path()
                if not dp:
                    raise TradeParseError("Demo file not found in the repo.")
                with open(dp, "rb") as fh:
                    daily, meta = load_trades_csv(fh.read())
            else:
                daily, meta = load_trades_csv(up.getvalue())
            ss.daily_pnls, ss.meta = daily, meta
            ss.used_demo = bool(use_demo)
            analytics.log_event("oa_parse_success", {"n_days": meta["n_days"]})
        except TradeParseError as e:
            analytics.log_event("oa_parse_failed")
            st.error(str(e))

    if ss.daily_pnls is None:
        st.button("Start over", on_click=_reset, key="oa_reset_top")
        return

    # --- 3) free preview ----------------------------------------------------
    if not ss.get("oa_preview"):
        ss["oa_preview"] = own_account.build_own_account_report(
            ss.daily_pnls, ss.meta,
            start_balance=float(start_balance),
            leverage=float(leverage),
            stop_out_pct=float(stop_out_pct),
        )
    rep = ss["oa_preview"]

    for w in (ss.meta or {}).get("warnings", []):
        st.info(w, icon="ℹ️")

    st.subheader("3 · Free preview")
    ss_score = rep.get("survival_score") or {}
    bands = rep.get("drawdown_bands") or {}
    kb = rep.get("killer_behavior") or {}
    pc1, pc2, pc3 = st.columns(3)
    score_val = ss_score.get("score")
    pc1.metric("Account Survival Score",
               "—" if score_val is None else f"{score_val}/100",
               ss_score.get("confidence", "Limited"))
    pc2.metric("Observed drawdown band",
               bands.get("observed_max_dd_band", "—"))
    pc3.metric("Killer behavior",
               kb.get("behavior", "—") if kb.get("available") else "—")
    st.caption("Bands are coarse on purpose. Estimated from uploaded "
               "history; not a forecast. Not trading advice.")
    st.divider()

    # --- 4) paywall / locked report -----------------------------------------
    if not ss.unlocked:
        st.subheader("4 · Early access — $9")
        st.info("**Candor is in early access.** The engine works, reports are real. "
                "$9 gets you a full report now + locked-in pricing when monitoring "
                "launches. Early access pricing won\u2019t last forever, but "
                "there\u2019s no fake countdown.", icon="🔦")
        if payments.mode() == "mock":
            st.warning("DEMO / TEST MODE — clicking below does **not** "
                       "charge anything. Live payments are not connected yet.", icon="⚠️")
        st.write("Locked: drawdown-band table, killer behavior detail, "
                 "margin pressure, what-if lab, personal risk-control "
                 "checklist, PDF.")
        _consent_payment = st.checkbox(PAY_CONSENT_TEXT,
                                       key="oa_consent_payment")
        btn_label = ("Unlock (demo — no charge)" if payments.mode() == "mock"
                     else "Get early access — $9")
        if st.button(btn_label, type="primary",
                     disabled=not _consent_payment, key="oa_unlock"):
            analytics.log_event("oa_unlock_clicked")
            if not ss.get("legal_logged_payment"):
                tracking.log_legal_acceptance(
                    source="payment", consent_text=PAY_CONSENT_TEXT,
                    report_id=rep.get("report_id"))
                ss["legal_logged_payment"] = True
            ss.checkout = payments.create_checkout(
                "full_report", success_url="?paid=1", cancel_url="?")
        if ss.checkout:
            if ss.checkout["checkout_url"] == "MOCK_CHECKOUT":
                if payments.verify_payment(ss.checkout["session_id"]):
                    ss.unlocked = True
                    analytics.log_event("oa_payment_success",
                                        {"product": "own_account_report"})
                    st.rerun()
            else:
                st.link_button("Complete payment",
                               ss.checkout["checkout_url"])
                st.caption("After paying you'll return here with the "
                           "report unlocked.")

    # --- 5) full report -----------------------------------------------------
    if ss.unlocked:
        analytics.log_event("oa_full_report_viewed")
        if not ss.report_id:
            ss.report_id = rep["report_id"]

        if not ss.logged:
            is_demo = bool(ss.get("used_demo", False))
            pay_status = ("demo" if is_demo else
                          ("mock" if payments.mode() == "mock" else "paid"))
            tracking.log_own_account_report(rep, pay_status, is_demo)
            ss.logged = True

        st.subheader("Full report")
        st.caption(f"Report ID {rep['report_id']} · {rep['generated']} · "
                   f"Confidence: {rep['confidence']}")

        # Data quality
        audit = rep["data_audit"]
        with st.expander(f"Data quality — confidence: {audit['confidence']}",
                         expanded=False):
            st.write(f"- Trades detected: {audit['n_trades']}")
            st.write(f"- Trading days: {audit['n_days']}")
            st.write(f"- Profitable days: {audit['profitable_days']}")
            st.write(f"- Large outliers: {audit['outliers']}")
            st.caption(audit["confidence_why"])

        # Drawdown bands table
        st.markdown("**Drawdown risk bands**")
        st.table([{
            "Threshold": f"{r['threshold_pct']}%",
            "Sensitivity band": r["band"],
            "Breached in history?": "Yes" if r["breached_in_history"] else "No",
        } for r in bands["rows"]])
        st.caption("Bands are coarse on purpose to avoid false precision. "
                   "Estimated from uploaded history; not a forecast.")

        # Killer behavior detail
        st.markdown("**🧬 Killer behavior**")
        if kb.get("available"):
            st.write(f"- Most dangerous behavior: **{kb['behavior']}** — "
                     f"{kb['note']}")
            m = kb["metrics"]
            st.write(f"- Longest losing streak: {m['longest_loss_streak']} "
                     f"days (sensitivity: {m['loss_streak_sensitivity']})")
            st.write(f"- Profit concentration: {m['concentration_label']}")
            st.write(f"- Risk drift over time: {m['drift_label']}")
            st.caption(kb["label"])
        else:
            st.caption(kb.get("note",
                              "Not enough data for a behavioral read."))

        # Margin pressure
        st.markdown("**⚖️ Margin pressure**")
        mp = rep["margin_pressure"]
        if mp.get("available"):
            st.write(f"- Observed equity floor: **{mp['observed_floor_pct']}%** "
                     "of starting balance")
            st.write(f"- Margin pressure band: **{mp['margin_pressure_band']}**")
            st.write(f"- Headroom vs {mp['stop_out_pct']}% stop-out: "
                     f"**{mp['stopout_headroom_band']}**")
            st.caption(mp["label"])
        else:
            st.caption(mp.get("note", ""))

        # What-if
        st.markdown("**🔬 What-if lab**")
        wif = rep["what_if"]
        st.table([{
            "Historical risk scaled to": f"{r['risk_pct']}%",
            "Observed drawdown band": r["observed_dd_band"],
        } for r in wif["rows"]])
        st.caption(wif["label"])

        # Instrument & session (V0: graceful)
        st.markdown("**📊 Instrument fit**")
        st.caption(rep["instrument_fit"]["note"])
        st.markdown("**🕐 Session risk**")
        st.caption(rep["session_risk"]["note"])

        # Checklist
        st.markdown("**🛡️ Personal risk-control checklist**")
        for it in rep["checklist"]["items"]:
            st.write(f"- {it}")
        st.caption(rep["checklist"]["label"])

        # PDF
        st.divider()
        try:
            pdf_bytes = build_own_account_pdf(rep)
            if st.download_button("Download PDF report",
                                  data=pdf_bytes,
                                  file_name=f"{rep['report_id']}_own_account.pdf",
                                  mime="application/pdf",
                                  key="oa_pdf_dl"):
                analytics.log_event("oa_pdf_downloaded")
                tracking.log_pdf_download(rep["report_id"])
        except Exception as _e:
            st.error(f"PDF generation failed: {_e}")

        st.caption("Your data is used only for this simulation. "
                   + rep["disclaimer"])

    st.divider()
    st.button("Start over", on_click=_reset, key="oa_reset_bot")



def pct(p):
    return f"{p * 100:.1f}%"


def pct_range(p, n_trades=None):
    """Display a pass-odds confidence band instead of false single-point precision.
    Presentation only — does NOT change the engine's computed probability.
    Band width reflects sample size: smaller samples → wider bands.
    """
    import math
    pp = max(0.0, min(1.0, float(p)))
    n = n_trades if (n_trades and n_trades > 0) else 60
    # ~80% confidence half-width via normal approx, floored so tiny samples stay honest
    half = 1.2816 * math.sqrt(pp * (1 - pp) / n)
    half = max(half, 0.04)  # never pretend to be tighter than ±4 points
    lo = max(0.0, pp - half)
    hi = min(1.0, pp + half)
    return f"{lo * 100:.0f}\u2013{hi * 100:.0f}%"


MARKET_OPTIONS = {
    "Forex / CFD firms": "cfd_forex",
    "Futures firms": "futures",
    "All firms": "all",
}


def _market_match(firm, market_class):
    if market_class == "all":
        return True
    return firm.get("instrument_class") == market_class


def _default_market_label(meta):
    """If the upload looks like MT4/MT5 (forex), default to Forex and keep
    futures firms off, so Apex doesn't pop up as a confusing 'best match'."""
    hint = (meta or {}).get("source_hint", "").lower()
    if "mt4" in hint or "mt5" in hint:
        return "Forex / CFD firms"
    return "All firms"


VERDICT_COPY = {
    "go":   ("Strong fit",
             "Historical pattern aligns well with this firm's published rules."),
    "wait": ("Borderline",
             "Historical pattern sits on the edge of this firm's published rules."),
    "skip": ("High mismatch",
             "Historical pattern shows a low fit with this firm's published rules."),
}

# --- header ------------------------------------------------------------------
_logo = _asset("candor-logo-primary-dark.png")
if _logo:
    st.image(_logo, width=300)
else:
    st.title("Candor")

# --- mode selector -----------------------------------------------------------
ss.setdefault("mode", "prop_firm")
_mode_label = st.radio(
    "Choose what to analyze",
    ["Prop Firm RealityCheck", "Own Account RealityCheck"],
    horizontal=True,
    index=(0 if ss.mode == "prop_firm" else 1),
    help=("Prop Firm: 'Can I pass this challenge?' · "
          "Own Account: 'Can my own account survive my trading?'"),
)
_new_mode = "own_account" if _mode_label.startswith("Own") else "prop_firm"
if _new_mode != ss.mode:
    # mode degisti -> daha onceki state'i temizle
    _reset()
    ss.mode = _new_mode

_sub_text = ("Own Account RealityCheck" if ss.mode == "own_account"
             else "Prop Firm RealityCheck")
_tagline = ("Candor · We don't sell guarantees — we tell you the odds. "
            "Statistical simulation only, not financial advice."
            if ss.mode == "prop_firm" else
            "Candor · Statistical risk diagnostics for your own MT4/MT5 "
            "account. No signals, no guarantees, no trading advice.")
st.markdown(
    "<div style='font-family:Georgia,serif;font-size:1.18rem;letter-spacing:.01em;"
    f"color:#D9A332;margin:.4rem 0 .15rem'>{_sub_text}</div>",
    unsafe_allow_html=True)
st.caption(_tagline)

# --- mode branch -------------------------------------------------------------
if ss.mode == "own_account":
    _render_own_account()
    st.stop()

firms = load_firms()

# --- 1) upload ---------------------------------------------------------------
st.subheader("1 · Upload your trading history")
st.write("Export a CSV from your platform. Currently supports: **MT4 / MT5 history "
         "export** and **generic CSV** with a profit column. Your file is used only "
         "for this simulation and is not stored.")

# Pre-upload consent (clickwrap, logged to Supabase on first valid upload)
_consent_upload = st.checkbox(
    "I understand this report is a statistical simulation and risk-diagnostics report, not financial, investment, or trading advice.",
    key="consent_upload")
if not _consent_upload:
    st.caption("Tick the box above to enable the upload.")

up = st.file_uploader("Trade history (.csv)", type=["csv"],
                       disabled=not _consent_upload)
col_a, col_b = st.columns([1, 1])
use_demo = col_b.button("Use demo data", disabled=not _consent_upload)

if (up is not None or use_demo) and ss.daily_pnls is None and _consent_upload:
    analytics.log_event("upload_started", {"demo": bool(use_demo)})
    # Real clickwrap record (once per session for upload-time consent)
    if not ss.get("legal_logged_upload"):
        tracking.log_legal_acceptance(
            source="upload",
            consent_text="I understand this report is a statistical simulation and risk-diagnostics report, not financial, investment, or trading advice.",
        )
        ss["legal_logged_upload"] = True
    try:
        if use_demo:
            dp = _demo_path()
            if not dp:
                raise TradeParseError("Demo file not found in the repo.")
            with open(dp, "rb") as fh:
                daily, meta = load_trades_csv(fh.read())
        else:
            daily, meta = load_trades_csv(up.getvalue())
        ss.daily_pnls, ss.meta = daily, meta
        ss.used_demo = bool(use_demo)
        ss.market_label = "All firms" if use_demo else _default_market_label(meta)
        analytics.log_event("parse_success", {"n_days": meta["n_days"]})
    except TradeParseError as e:
        analytics.log_event("parse_failed")
        st.error(str(e))

# --- 2) market filter + build preview ----------------------------------------
if ss.daily_pnls is not None:
    labels = list(MARKET_OPTIONS.keys())
    idx = labels.index(ss.market_label) if ss.market_label in labels else len(labels) - 1
    chosen = st.radio("Which firms to test?", labels, index=idx, horizontal=True,
                      help="MT4/MT5 (forex) uploads default to Forex/CFD firms so "
                           "futures firms like Apex don't show as a confusing best match.")
    if chosen != ss.market_label:
        ss.market_label = chosen
        ss.preview = None  # market changed -> recompute

    market_class = MARKET_OPTIONS[ss.market_label]
    filtered = [f for f in firms if _market_match(f, market_class)]

    # --- account-size selector (presentation only; odds are % based) --------
    _sizes = available_account_sizes(filtered)
    if _sizes:
        _size_labels = [f"${s_//1000}K" for s_ in _sizes]
        # default to 50K if available, else the middle option
        if ss.account_size in _sizes:
            _sidx = _sizes.index(ss.account_size)
        elif 50000 in _sizes:
            _sidx = _sizes.index(50000)
        else:
            _sidx = len(_sizes) // 2
        _chosen_label = st.radio("Account size to simulate", _size_labels,
                                 index=_sidx, horizontal=True,
                                 help="Your trade history is fixed in dollars, but targets and "
                                      "limits are percentages — so a smaller account usually means "
                                      "your same dollar P/L clears the target more easily. Size "
                                      "changes both your pass-odds and the challenge fee.")
        _chosen_size = _sizes[_size_labels.index(_chosen_label)]
        if _chosen_size != ss.account_size:
            ss.account_size = _chosen_size
            ss.preview = None  # size changed -> recompute
        # rebase every firm to the chosen size
        filtered = [apply_account_size(f, ss.account_size) for f in filtered]
        # honesty: warn if any shown firm's fee at this size is estimated
        if any(f.get("_fee_estimated") and f.get("_selected_size") == ss.account_size
               for f in filtered):
            st.caption("ⓘ Some fees at this size are estimated from typical pricing and "
                       "marked pending verification. Pass-odds are unaffected.")

    if not filtered:
        st.warning("No firms in this category yet.")
    elif ss.preview is None or ss.preview_market != ss.market_label:
        ss.preview = build_preview(ss.daily_pnls, filtered, ss.meta)
        ss.preview_market = ss.market_label
        analytics.log_event("preview_viewed")
    if ss.preview is None:
        st.button("Start over", on_click=_reset)
        st.stop()
    p = ss.preview
    for w in p["data"].get("warnings", []):
        st.info(w, icon="ℹ️")

    st.subheader("2 · Your free preview")
    _n = p["data"].get("n_trades")
    _killer_found = bool(p.get("killer_rule"))
    c1, c2, c3 = st.columns(3)
    c1.metric("Killer rule", "Detected" if _killer_found else "None flagged")
    c2.metric("Best-match fit", VERDICT_COPY[p["verdict"]][0])
    c3.metric("Pass-odds ranges", "🔒 Locked")

    vlabel, vmsg = VERDICT_COPY[p["verdict"]]
    st.markdown(f"**Your best-match fit:** {vlabel} — {vmsg}")
    st.info("🔒 The free preview shows **whether** a killer rule was found and your "
            "overall fit. **Which rule, which ruleset, and your pass-odds ranges** "
            "are in the full report.", icon="🔒")

    st.divider()

    # --- 3) paywall / locked full report ------------------------------------
    if not ss.unlocked:
        st.subheader("3 · Early access — $9")
        st.info("**Candor is in early access.** The engine works, reports are real. "
                "$9 gets you a full report now + locked-in pricing when monitoring "
                "launches. Early access pricing won\u2019t last forever, but "
                "there\u2019s no fake countdown.", icon="🔦")
        if payments.mode() == "mock":
            st.warning("DEMO / TEST MODE — clicking below does **not** charge "
                       "anything. Live payments are not connected yet.", icon="⚠️")
        st.write("Locked: every firm scored · killer rule per firm · expected fee burn "
                 "· **what-if simulator** · daily breakdown · equity curve · PDF.")
        # blurred teaser (ranges, no single-point numbers, no real firm names)
        st.markdown(
            "<div style='filter:blur(5px);opacity:.55;pointer-events:none;"
            "border:1px solid #ddd4c3;border-radius:6px;padding:14px'>"
            "Ruleset A 55–70% · Ruleset B 20–35% · Ruleset C 2–9% &nbsp;|&nbsp; "
            "what-if: 100%→55–70%, 80%→48–63%, 65%→38–54% · fee burn per ruleset · equity curve</div>",
            unsafe_allow_html=True)
        st.write("")

        _consent_payment = st.checkbox(
            "Digital report. Statistical simulation only. No guaranteed outcome. Sales are generally final after report generation.",
            key="consent_payment")

        btn_label = ("Unlock (demo — no charge)" if payments.mode() == "mock"
                     else "Get early access — $9")
        if st.button(btn_label, type="primary", disabled=not _consent_payment):
            analytics.log_event("unlock_clicked")
            # Real clickwrap record (payment-time consent)
            if not ss.get("legal_logged_payment"):
                tracking.log_legal_acceptance(
                    source="payment",
                    consent_text="Digital report. Statistical simulation only. No guaranteed outcome. Sales are generally final after report generation.",
                    report_id=ss.get("report_id"),
                )
                ss["legal_logged_payment"] = True
            ss.checkout = payments.create_checkout(
                "full_report", success_url="?paid=1", cancel_url="?")

        if ss.checkout:
            if ss.checkout["checkout_url"] == "MOCK_CHECKOUT":
                if payments.verify_payment(ss.checkout["session_id"]):
                    ss.unlocked = True
                    analytics.log_event("payment_success", {"product": "full_report"})
                    st.rerun()
            else:
                st.link_button("Complete payment", ss.checkout["checkout_url"])
                st.caption("After paying you'll return here with the report unlocked.")

    # --- 4) full report ------------------------------------------------------
    if ss.unlocked:
        analytics.log_event("full_report_viewed")
        if not ss.report_id:
            ss.report_id = tracking.make_report_id()
        full = build_full_report(p, ss.daily_pnls, report_id=ss.report_id)

        # persist the report once (Supabase if configured, else local fallback)
        if not ss.logged:
            is_demo = (ss.market_label == "All firms" and ss.get("used_demo", False))
            pay_status = ("demo" if is_demo else
                          ("mock" if payments.mode() == "mock" else "paid"))
            tracking.log_report(full, ss.market_label, pay_status, is_demo)
            ss.logged = True

        st.subheader("Full report")
        st.caption(f"Report ID {full['report_id']} · {full['ruleset_version']} · "
                   f"Confidence: {full['confidence']}")
        st.write(f"Generated {full['generated']} · {full['data']['n_trades']} trades · "
                 f"{full['data']['n_days']} trading days")

        _dq = full["data_audit"]
        with st.expander(f"Data quality — confidence: {_dq['confidence']}", expanded=False):
            st.write(f"- Trades detected: {_dq['n_trades']}")
            st.write(f"- Trading days: {_dq['n_days']}")
            st.write(f"- Profitable days: {_dq['profitable_days']}")
            st.write(f"- Large outliers: {_dq['outliers']}")
            st.caption(_dq["confidence_why"])

        _nt = full["data"]["n_trades"]
        st.markdown("**All firms** — pass odds shown as 80% confidence ranges")
        st.table([{
            "Firm": r["firm"], "Pass odds": pct_range(r["pass_prob"], _nt),
            "Risk label": VERDICT_COPY.get(r["verdict"], ("—",""))[0], "Killer rule": r["killer_rule"],
            "Fee": f"${r['fee']:,}",
        } for r in full["firm_rows"]])
        st.caption(f"Ranges are 80% confidence bands from {_nt} trades; more trades narrow them. Not single-point certainty.")
        if any(r.get("verification_status") == "needs_verification"
               for r in full["firm_rows"]):
            st.caption("⚠️ Some rulesets are seed data pending verification. "
                       "Treat numbers as estimates until each firm's rules are confirmed.")

        # --- Killer Rule Autopsy (the wow screen) ---------------------------
        _au = full["autopsy"]
        st.markdown(f"### 🔎 Killer Rule Autopsy — {_au['rule']}")
        st.write(_au["mechanism"])
        if _au["path"]:
            st.write("**How it usually happens:** " + " → ".join(_au["path"]))
        if _au["reduce"]:
            st.write("**What reduces this risk:**")
            for x in _au["reduce"]:
                st.write(f"- {x}")
        st.caption(_au["label"])

        st.markdown("**Expected fee burn**")
        _fb = full["fee_burn_headline"]
        st.caption(_fb["note"])
        for r in full["firm_rows"]:
            st.write(f"- {r['firm']}: {r['fee_burn_msg']}  ·  retry danger: **{r['retry_danger']}**")

        # --- Best-fit firm matchmaker ---------------------------------------
        _mm = full["matchmaker"]
        if _mm:
            st.markdown("**Best-fit challenge type**")
            c1, c2 = st.columns(2)
            c1.write(f"✅ **Best fit — {_mm['best_firm']}** ({pct_range(_mm['best_odds'], _nt)})")
            for x in _mm["best_why"]:
                c1.write(f"- {x}")
            c2.write(f"⚠️ **Lowest fit — {_mm['worst_firm']}** ({pct_range(_mm['worst_odds'], _nt)})")
            for x in _mm["worst_why"]:
                c2.write(f"- {x}")
            st.caption(_mm["label"])

        st.markdown(f"**What-if simulator — {full['what_if']['firm']}**")
        st.caption(full["what_if"]["label"])
        st.table([{
            "Risk level": f"{row['risk_pct']}%",
            "Estimated pass odds": pct_range(row["pass_prob"], _nt),
            "Killer rule": row["killer_rule_label"],
        } for row in full["what_if"]["rows"]])

        if full["equity_curve"]:
            start_bal = full.get("equity_start", full["equity_curve"][0])
            st.markdown(f"**Account equity — one simulated attempt** "
                        f"(starts at your ${start_bal:,.0f} balance)")
            st.line_chart({"Account equity ($)": full["equity_curve"]})
            st.caption("This is account balance over the attempt, not cumulative P/L.")

        # --- Risk DNA ---------------------------------------------------------
        _dna = full["risk_dna"]
        st.markdown("**🧬 Your Risk DNA**")
        if _dna.get("available"):
            m = _dna["metrics"]
            st.write(f"- Most dangerous behavior: **{_dna['most_dangerous_behavior']}** — {_dna['behavior_note']}")
            st.write(f"- Longest losing streak: {m['longest_loss_streak']} days "
                     f"(sensitivity: {m['loss_streak_sensitivity']})")
            st.write(f"- Profit concentration: {m['concentration_label']} "
                     f"(best day = {int(m['profit_concentration']*100)}% of gains)")
            st.write(f"- Risk drift over time: {m['drift_label']}")
            st.caption(_dna["label"])
        else:
            st.caption(_dna.get("note", "Not enough data for a behavioral read."))

        # --- Rule interaction -----------------------------------------------
        _ri = full.get("rule_interaction") or {}
        if _ri.get("compound_label"):
            st.markdown("**⚙️ Rule interaction — how rules compound**")
            _cpct = _ri.get("compound_breach_pct", 0)
            _spct = _ri.get("solo_breach_pct", 0)
            ri1, ri2 = st.columns(2)
            ri1.metric("Compound failures",
                       f"{_cpct*100:.0f}%",
                       help="Failures where 2+ rules fired near-simultaneously. "
                            "High = the ruleset has a compounding structure.")
            ri2.metric("Single-rule failures",
                       f"{_spct*100:.0f}%",
                       help="Failures caused by one rule alone.")
            st.write(f"- {_ri['compound_label']}")
            for trap in (_ri.get("trap_labels") or []):
                st.write(f"- ⚠️ {trap}")
            if _ri.get("active_rules"):
                st.caption("Active rules in this ruleset: " +
                           " · ".join(_ri["active_rules"]))
            st.caption("Rule-interaction analysis on your uploaded history. "
                       "Diagnostic only, not advice.")

        # --- Sequence risk (path-dependency) --------------------------------
        _seq = full.get("sequence_risk") or {}
        _stk = _seq.get("streak") or {}
        st.markdown("**🔀 Sequence risk — the order, not just the average**")
        if _seq.get("label"):
            _osens = _seq["order_sensitivity"]
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("Avg pass (any order)",
                       f"{_seq['pass_rate_shuffled']*100:.0f}%")
            sc2.metric("Unluckiest 25% of orders",
                       f"{_seq['worst_quartile_pass']*100:.0f}%")
            sc3.metric("Order sensitivity",
                       f"{_osens*100:.0f}%",
                       help="Gap between a lucky and an unlucky ordering of the "
                            "very same trading days. High = your risk is the run, "
                            "not the average.")
            st.write(f"- {_seq['label']}")
            if _stk.get("lag1_autocorr") is not None:
                st.write(f"- Your results' streakiness (lag-1 autocorrelation): "
                         f"**{_stk['lag1_autocorr']:+.2f}** — "
                         f"longest observed runs: {_stk['longest_win_streak']} up, "
                         f"{_stk['longest_loss_streak']} down.")
            st.write(f"- When a bad ordering breaks this ruleset, the rule that "
                     f"usually does it: **{_seq['dominant_breach_label']}**.")
            st.caption("Same days, same totals — only the order changes. This "
                       "isolates run-of-the-cards risk that a single win-rate "
                       "can't show. Diagnostic only, not advice.")
        else:
            st.caption(_stk.get("label", "Not enough data for a sequence read."))

        # --- Personal danger rules -------------------------------------------
        _dr = full["danger_rules"]
        st.markdown("**🛡️ Your personal danger rules**")
        for r in _dr["rules"]:
            st.write(f"- {r}")
        st.caption(_dr["label"])

        # --- email capture (optional, before download) ----------------------
        st.divider()
        st.markdown("**Email me this report (optional)**")
        ec1, ec2 = st.columns([3, 1])
        email = ec1.text_input("Email", label_visibility="collapsed",
                               placeholder="you@example.com", key="email_input")
        if ec2.button("Send"):
            if tracking.log_lead(email, full["report_id"], "report"):
                st.success("Saved. (We'll email this report and rule-change alerts.)")
            else:
                st.error("That doesn't look like a valid email.")

        pdf_bytes = build_pdf(full)
        if st.download_button("Download PDF report", data=pdf_bytes,
                              file_name=f"{full['report_id']}.pdf",
                              mime="application/pdf"):
            analytics.log_event("pdf_downloaded")
            tracking.log_pdf_download(full["report_id"])

        st.divider()
        st.subheader("Keep going")
        cc1, cc2 = st.columns(2)
        if cc1.button("Rerun with new data — $9"):
            analytics.log_event("rerun_clicked")
            st.info("Upload a new CSV to compare before / after.")
        cc2.button("Bundle · 3 reports — $49")

        # --- Watchtower waitlist --------------------------------------------
        st.markdown("**Candor Watchtower — get alerted when a firm's rules change**")
        st.caption("Prop firms change their rules. When they do, your pass odds change. "
                   "Join the waitlist for rule-change alerts + reruns (coming soon).")
        wc1, wc2 = st.columns([3, 1])
        wl_email = wc1.text_input("Watchtower email", label_visibility="collapsed",
                                  placeholder="you@example.com", key="watch_input")
        if wc2.button("Join waitlist"):
            if tracking.log_watchtower_signup(wl_email, full["report_id"],
                                              full["ruleset_version"]):
                st.success("You're on the Watchtower waitlist.")
            else:
                st.error("That doesn't look like a valid email.")

        st.divider()
        oc1, oc2 = st.columns(2)
        oc1.markdown(f"[Submit your outcome when it ends →](./?page=outcome&report_id={full['report_id']})")
        oc2.markdown("[See the Honesty Ledger →](./?page=honesty-ledger)")

        st.caption("Your data is used only for this simulation. " + full["disclaimer"])

    st.divider()
    st.button("Start over", on_click=_reset)
