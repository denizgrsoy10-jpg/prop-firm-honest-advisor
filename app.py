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

from rules_engine import load_firms
from load_trades import load_trades_csv, TradeParseError
from report_builder import build_preview, build_full_report
from pdf_export import build_pdf
import payments
import analytics
import tracking

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
ss.setdefault("daily_pnls", None)
ss.setdefault("meta", None)
ss.setdefault("preview", None)
ss.setdefault("unlocked", False)
ss.setdefault("checkout", None)
ss.setdefault("market_label", None)
ss.setdefault("preview_market", None)
ss.setdefault("report_id", None)
ss.setdefault("logged", False)
ss.setdefault("used_demo", False)


def _reset():
    for k in ("daily_pnls", "meta", "preview", "checkout", "market_label",
              "preview_market", "report_id"):
        ss[k] = None
    ss["unlocked"] = False
    ss["logged"] = False


def _demo_path():
    """Find the demo CSV whether it's in data/ or sitting flat in the repo root."""
    base = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(base, "data", "demo_trades.csv"),
              os.path.join(base, "demo_trades.csv")):
        if os.path.exists(p):
            return p
    return None


def pct(p):
    return f"{p * 100:.1f}%"


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
    "go": ("Go", "Worth attempting on this data."),
    "wait": ("Wait", "Borderline — tighten up before you pay."),
    "skip": ("Skip", "Don't pay for this one yet."),
}

# --- header ------------------------------------------------------------------
_logo = _asset("candor-logo-primary-dark.png")
if _logo:
    st.image(_logo, width=300)
else:
    st.title("Candor")
st.markdown(
    "<div style='font-family:Georgia,serif;font-size:1.18rem;letter-spacing:.01em;"
    "color:#D9A332;margin:-.35rem 0 .15rem'>Prop Firm RealityCheck</div>",
    unsafe_allow_html=True)
st.caption("Candor · We don't sell guarantees — we tell you the odds. "
           "Statistical simulation only, not financial advice.")

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
    lo, hi = p["odds_range"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Best matching firm", p["best_firm"].split(" — ")[0], pct(p["best_prob"]))
    c2.metric("Toughest firm", p["worst_firm"].split(" — ")[0], pct(p["worst_prob"]))
    c3.metric("Pass-odds range", f"{pct(lo)}–{pct(hi)}")

    vlabel, vmsg = VERDICT_COPY[p["verdict"]]
    st.markdown(f"**Verdict on your best match:** {vlabel} — {vmsg}")
    st.markdown(f"**Most dangerous rule for you:** {p['killer_rule']}")

    st.divider()

    # --- 3) paywall / locked full report ------------------------------------
    if not ss.unlocked:
        st.subheader("3 · Unlock the full report — $19")
        if payments.mode() == "mock":
            st.warning("DEMO / TEST MODE — clicking unlock does **not** charge "
                       "anything and is not a real purchase. Live payments are not "
                       "connected yet.", icon="⚠️")
        st.write("Locked: every firm scored · killer rule per firm · expected fee burn "
                 "· **what-if simulator** · daily breakdown · equity curve · PDF.")
        # blurred teaser
        st.markdown(
            "<div style='filter:blur(5px);opacity:.55;pointer-events:none;"
            "border:1px solid #ddd4c3;border-radius:6px;padding:14px'>"
            "FTMO 58% · The5ers 34% · Apex 14% &nbsp;|&nbsp; what-if: 100%→58%, "
            "80%→63%, 65%→66% · fee burn per firm · equity curve</div>",
            unsafe_allow_html=True)
        st.write("")

        _consent_payment = st.checkbox(
            "Digital report. Statistical simulation only. No guaranteed outcome. Sales are generally final after report generation.",
            key="consent_payment")

        btn_label = ("Unlock (demo — no charge)" if payments.mode() == "mock"
                     else "Unlock full report — $19")
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

        st.markdown("**All firms**")
        st.table([{
            "Firm": r["firm"], "Pass odds": pct(r["pass_prob"]),
            "Verdict": r["verdict"].upper(), "Killer rule": r["killer_rule"],
            "Fee": f"${r['fee']:,}",
        } for r in full["firm_rows"]])
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
            c1.write(f"✅ **Best fit — {_mm['best_firm']}** ({pct(_mm['best_odds'])})")
            for x in _mm["best_why"]:
                c1.write(f"- {x}")
            c2.write(f"⚠️ **Avoid — {_mm['worst_firm']}** ({pct(_mm['worst_odds'])})")
            for x in _mm["worst_why"]:
                c2.write(f"- {x}")
            st.caption(_mm["label"])

        st.markdown(f"**What-if simulator — {full['what_if']['firm']}**")
        st.caption(full["what_if"]["label"])
        st.table([{
            "Risk level": f"{row['risk_pct']}%",
            "Estimated pass odds": pct(row["pass_prob"]),
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
        if cc1.button("Rerun after tweaking strategy — $9"):
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
