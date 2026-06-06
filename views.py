"""
views.py — extra pages reached via ?page=... query param from app.py.
Kept out of the main funnel file for clarity. No engine logic here.
"""
from __future__ import annotations
import os
import streamlit as st

import tracking
import signal_scan

FAILED_RULES = ["Daily loss limit", "Max drawdown", "Trailing drawdown",
                "Profit target not reached", "Consistency rule", "News rule", "Other"]


def _back():
    st.markdown("[← Back to RealityCheck](./)")


# --------------------------------------------------------------- /outcome
def render_outcome(report_id_default=""):
    st.title("Submit your outcome")
    st.caption("Candor measures its own predictions. When your challenge resolves, "
               "tell us what actually happened — it powers the public Honesty Ledger.")
    rid = st.text_input("Report ID", value=report_id_default or "",
                        placeholder="CND-YYYYMMDD-xxxxxx")
    result = st.radio("What happened?",
                      ["passed", "failed", "not_attempted", "abandoned"],
                      format_func=lambda x: x.replace("_", " ").title())

    payload = {"report_id": rid.strip(), "result": result,
               "attempted": result in ("passed", "failed", "abandoned")}

    if result == "failed":
        payload["failed_rule"] = st.selectbox("Which rule failed?", FAILED_RULES)
        payload["failed_day"] = st.number_input("Roughly which day did it fail?",
                                                min_value=0, max_value=400, value=0, step=1)
        payload["phase_reached"] = st.text_input("Phase reached (optional)",
                                                 placeholder="e.g. Phase 1 / Evaluation")
    if result in ("passed", "failed", "abandoned"):
        c1, c2 = st.columns(2)
        payload["firm_attempted"] = c1.text_input("Firm attempted (optional)")
        payload["product_attempted"] = c2.text_input("Product (optional)")
    if result == "passed":
        payload["payout_received"] = st.checkbox("Reached a payout?")
    payload["user_note"] = st.text_area("Anything else? (optional)", height=80)
    email = st.text_input("Email (optional — only if you want a reply)")
    if email:
        payload["email"] = email.strip()
    consent = st.checkbox("Allow Candor to use this outcome anonymously to publish "
                          "calibration stats.", value=True)
    payload["consent_to_anonymous_use"] = bool(consent)

    if st.button("Submit outcome", type="primary"):
        if not rid.strip():
            st.error("Please enter your Report ID (it's on your report / PDF).")
        else:
            tracking.log_outcome(payload)
            st.success("Recorded. Thank you — this is exactly what lets us grade "
                       "ourselves honestly.")
    _back()


# --------------------------------------------------------- /honesty-ledger
def render_ledger():
    st.title("Candor Honesty Ledger")
    s = tracking.ledger_public_stats()
    st.caption(f"Verified trader outcomes collected so far: {s['total_outcomes']} "
               f"/ {s['min_required']} needed to publish.")
    if not s["ready"]:
        st.info("**Collecting verified outcomes.** Public calibration — killer-rule "
                "accuracy, pass-odds bucket accuracy, GO/WAIT/SKIP hit rates, and "
                "firm-by-firm calibration — will appear once enough users submit real "
                "results. We will not show accuracy numbers until the data supports them.")
        st.progress(min(1.0, s["total_outcomes"] / max(1, s["min_required"])))
    else:
        st.success("Threshold reached — calibration tables are being prepared from "
                   "verified outcomes. (No estimates are shown until each bucket has "
                   f"at least {tracking.LEDGER_MIN_PER_BUCKET} outcomes.)")
    st.caption("We do not hide from our predictions.")
    _back()


# ----------------------------------------------------------------- /admin
def render_admin():
    st.title("Candor — Admin Command Center")
    pw_env = os.environ.get("ADMIN_PASSWORD")
    if not pw_env:
        st.warning("Admin is disabled until ADMIN_PASSWORD is set in Secrets.")
        return
    pw = st.text_input("Password", type="password")
    if pw != pw_env:
        if pw:
            st.error("Wrong password.")
        return

    a = tracking.admin_stats()
    st.caption(f"Storage backend: **{a['backend']}**"
               + ("  ⚠️ local (ephemeral) — set Supabase secrets for real persistence."
                  if a["backend"] == "local" else "  ✓ persistent"))
    c = st.columns(4)
    c[0].metric("Reports", a["total_reports"])
    c[1].metric("Leads", a["leads"])
    c[2].metric("PDF downloads", a["pdf_downloads"])
    c[3].metric("Outcomes", a["outcomes"])
    c = st.columns(4)
    c[0].metric("Real (non-demo)", a["real_reports"])
    c[1].metric("Watchtower", a["watchtower"])
    c[2].metric("Signal scans", a["signal_scans"])

    st.markdown("**Most common killer rule**")
    st.table([{"Killer rule": k, "Count": v} for k, v in list(a["killer_rule_dist"].items())[:8]] or [{"Killer rule": "—", "Count": 0}])
    st.markdown("**Best-firm distribution**")
    st.table([{"Best firm": k, "Count": v} for k, v in list(a["best_firm_dist"].items())[:8]] or [{"Best firm": "—", "Count": 0}])
    st.markdown("**Payment status**")
    st.table([{"Status": k, "Count": v} for k, v in a["payment_dist"].items()] or [{"Status": "—", "Count": 0}])
    st.markdown("**Recent reports**")
    st.table([{"Report ID": r.get("report_id"), "When": r.get("created_at"),
               "Best": r.get("best_firm"), "Verdict": r.get("verdict"),
               "Pay": r.get("payment_status")} for r in a["recent"]] or [{"Report ID": "—"}])


# ----------------------------------------------------------------- /signal
def render_signal():
    st.title("Candor Signal Scanner")
    st.caption("Paste a trading 'signal' and Candor flags missing risk hygiene and "
               "hype language. It does NOT tell you whether the trade is good.")
    txt = st.text_area("Paste the signal text", height=140,
                       placeholder="e.g. GOLD buy now, no SL, target 1000 pips, guaranteed")
    opt_in = st.checkbox("Email me when the full Signal Scanner launches")
    email = st.text_input("Email (optional)") if opt_in else ""
    if st.button("Scan signal", type="primary"):
        if not txt.strip():
            st.error("Paste a signal first.")
        else:
            res = signal_scan.scan_signal(txt)
            color = {"High Risk": "🔴", "Suspicious": "🟠", "Clean-ish": "🟢"}.get(res["risk_level"], "⚪")
            st.subheader(f"{color} {res['risk_level']} · risk score {res['risk_score']}/100")
            if res["red_flags"]:
                st.markdown("**Red flags:**")
                for f in res["red_flags"]:
                    st.write(f"- {f}")
            else:
                st.write("No obvious red flags in the checklist.")
            st.caption(res["label"])
            tracking.log_signal_scan({
                "email": (email.strip() or None), "pasted_text_hash": res["text_hash"],
                "risk_level": res["risk_level"], "red_flags": ", ".join(res["red_flags"]),
                "waitlist_opt_in": bool(opt_in),
            })
    _back()
