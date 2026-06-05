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
import streamlit as st

from rules_engine import load_firms
from load_trades import load_trades_csv, TradeParseError
from report_builder import build_preview, build_full_report
from pdf_export import build_pdf
import payments
import analytics

st.set_page_config(page_title="Prop Firm RealityCheck — Candor", layout="centered")

# --- session state -----------------------------------------------------------
ss = st.session_state
ss.setdefault("daily_pnls", None)
ss.setdefault("meta", None)
ss.setdefault("preview", None)
ss.setdefault("unlocked", False)
ss.setdefault("checkout", None)


def _reset():
    for k in ("daily_pnls", "meta", "preview", "unlocked", "checkout"):
        ss[k] = None if k != "unlocked" else False


def pct(p):
    return f"{p * 100:.0f}%"


VERDICT_COPY = {
    "go": ("Go", "Worth attempting on this data."),
    "wait": ("Wait", "Borderline — tighten up before you pay."),
    "skip": ("Skip", "Don't pay for this one yet."),
}

# --- header ------------------------------------------------------------------
st.title("Prop Firm RealityCheck")
st.caption("Candor · We don't sell guarantees — we tell you the odds. "
           "Statistical simulation only, not financial advice.")

firms = load_firms()

# --- 1) upload ---------------------------------------------------------------
st.subheader("1 · Upload your trading history")
st.write("Export a CSV from your platform. Currently supports: **MT4 / MT5 history "
         "export** and **generic CSV** with a profit column. Your file is used only "
         "for this simulation and is not stored.")

up = st.file_uploader("Trade history (.csv)", type=["csv"])
col_a, col_b = st.columns([1, 1])
use_demo = col_b.button("Use demo data")

if (up is not None or use_demo) and ss.preview is None:
    analytics.log_event("upload_started", {"demo": bool(use_demo)})
    try:
        if use_demo:
            with open("data/demo_trades.csv", "rb") as fh:
                daily, meta = load_trades_csv(fh.read())
        else:
            daily, meta = load_trades_csv(up.getvalue())
        ss.daily_pnls, ss.meta = daily, meta
        ss.preview = build_preview(daily, firms, meta)
        analytics.log_event("parse_success", {"n_days": meta["n_days"]})
        analytics.log_event("preview_viewed")
    except TradeParseError as e:
        analytics.log_event("parse_failed")
        st.error(str(e))

# --- 2) free preview ---------------------------------------------------------
if ss.preview:
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

        if st.button("Unlock full report — $19", type="primary"):
            analytics.log_event("unlock_clicked")
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
        full = build_full_report(p, ss.daily_pnls)

        st.subheader("Full report")
        st.write(f"Generated {full['generated']} · {full['data']['n_trades']} trades · "
                 f"{full['data']['n_days']} trading days")

        st.markdown("**All firms**")
        st.table([{
            "Firm": r["firm"], "Pass odds": pct(r["pass_prob"]),
            "Verdict": r["verdict"].upper(), "Killer rule": r["killer_rule"],
            "Fee": f"${r['fee']:,}",
        } for r in full["firm_rows"]])

        st.markdown("**Expected fee burn**")
        for r in full["firm_rows"]:
            st.write(f"- {r['firm']}: {r['fee_burn_msg']}")

        st.markdown(f"**What-if simulator — {full['what_if']['firm']}**")
        st.caption(full["what_if"]["label"])
        st.table([{
            "Risk level": f"{row['risk_pct']}%",
            "Estimated pass odds": pct(row["pass_prob"]),
            "Killer rule": row["killer_rule_label"],
        } for row in full["what_if"]["rows"]])

        if full["equity_curve"]:
            st.markdown("**Sample equity curve (one simulated attempt)**")
            st.line_chart(full["equity_curve"])

        pdf_bytes = build_pdf(full)
        if st.download_button("Download PDF report", data=pdf_bytes,
                              file_name="prop-firm-realitycheck.pdf",
                              mime="application/pdf"):
            analytics.log_event("pdf_downloaded")

        st.divider()
        st.subheader("Keep going")
        cc1, cc2 = st.columns(2)
        if cc1.button("Rerun after tweaking strategy — $9"):
            analytics.log_event("rerun_clicked")
            st.info("Upload a new CSV to compare before / after.")
        cc2.button("Bundle · 3 reports — $49")

        st.caption("Your data is used only for this simulation. " + full["disclaimer"])

    st.divider()
    st.button("Start over", on_click=_reset)
