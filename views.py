"""
views.py — extra pages reached via ?page=... query param from app.py.
Kept out of the main funnel file for clarity. No engine logic here.
"""
from __future__ import annotations
import os
import streamlit as st

import tracking
import signal_scan
import growth

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


# -------------------------------------------------------------- /autopilot
def render_autopilot():
    """Internal Growth Autopilot console. Admin-gated. No public exposure."""
    st.title("Candor — Growth Autopilot")
    st.caption("Internal marketing console · Approved content in, safe distribution out. "
               "No spam · no browser automation · official-API-ready.")

    pw_env = os.environ.get("ADMIN_PASSWORD")
    if not pw_env:
        st.warning("Autopilot is disabled until ADMIN_PASSWORD is set in Secrets.")
        return
    pw = st.text_input("Password", type="password")
    if pw != pw_env:
        if pw:
            st.error("Wrong password.")
        return

    ov = growth.autopilot_overview()
    v = ov["vault"]
    c = st.columns(4)
    c[0].metric("Approved", v["approved"])
    c[1].metric("Drafts", v["draft"])
    c[2].metric("Queued", ov["queued"])
    c[3].metric("Published (log)", ov["publish_log"])
    if v["risky"]:
        st.error(f"⚠️ {v['risky']} item(s) flagged risky by Compliance Guard — these can't be approved or published.")

    tabs = st.tabs(["Vault", "Compliance", "Schedule", "UTM",
                    "Templates", "Daily Plan", "Influencers", "Reddit Scout", "Channels"])

    # --- Vault ---
    with tabs[0]:
        st.subheader("Approved Content Vault")
        with st.form("add_content", clear_on_submit=True):
            ctype = st.selectbox("Type", growth.CONTENT_TYPES)
            title = st.text_input("Title")
            hook = st.text_input("Hook (optional)")
            body = st.text_area("Body")
            cta = st.text_input("CTA (optional)")
            if st.form_submit_button("Add as draft", type="primary"):
                row = growth.add_content(ctype, title, body, hook, cta)
                if row["compliance_status"] == "risky":
                    st.error(f"Saved as draft but flagged RISKY: {row['compliance_flags']}. "
                             "Rewrite before approving.")
                else:
                    st.success("Draft added (compliance: clean).")
        st.markdown("**Content items**")
        items = growth.list_content(limit=200)
        if not items:
            st.caption("No content yet.")
        for it in items:
            cols = st.columns([3, 1, 1, 1])
            cols[0].write(f"**{it.get('title') or '(no title)'}** · _{it.get('type')}_")
            cols[1].write(it.get("status"))
            cols[2].write("🔴 risky" if it.get("compliance_status") == "risky" else "🟢 clean")
            if it.get("status") == "draft" and it.get("compliance_status") != "risky":
                if cols[3].button("Approve", key="ap_" + it.get("content_id", "")):
                    res = growth.approve_content(it["content_id"])
                    st.success("Approved.") if res["ok"] else st.error(res["reason"])
                    st.rerun()

    # --- Compliance ---
    with tabs[1]:
        st.subheader("Compliance Guard")
        st.caption("Paste any copy to check it against banned phrases before using it.")
        txt = st.text_area("Copy to check", height=120)
        if st.button("Check compliance"):
            res = growth.check_compliance(txt)
            if res["status"] == "risky":
                st.error("RISKY — found: " + ", ".join(res["flags"]))
                st.markdown("**Use safe Candor language instead:**")
                for s in res["suggestions"]:
                    st.write(f"- {s}")
            else:
                st.success("Clean — no banned phrases.")
        st.markdown("**Banned phrases**")
        st.caption(", ".join(growth.BANNED_PHRASES))

    # --- Schedule ---
    with tabs[2]:
        st.subheader("Timezone Scheduler")
        st.caption("Only approved, compliant content can be queued.")
        approved = [i for i in growth.list_content(limit=500) if i.get("status") == "approved"]
        if not approved:
            st.info("Approve some content first.")
        else:
            with st.form("sched", clear_on_submit=True):
                pick = st.selectbox("Content", [f"{i['title']} · {i['content_id']}" for i in approved])
                ch = st.selectbox("Channel", list(growth.CHANNEL_DEFAULTS.keys()))
                region = st.selectbox("Region", list(growth.REGION_OFFSETS.keys()))
                when = st.text_input("Scheduled time (UTC ISO)", value=growth.db.now_iso())
                if st.form_submit_button("Queue"):
                    cid = pick.split("·")[-1].strip()
                    res = growth.schedule_content(cid, ch, region, when)
                    st.success("Queued.") if res["ok"] else st.error(res["reason"])
        st.markdown("**Next in queue**")
        sc = growth.list_schedule(limit=100)
        st.table([{"When (UTC)": s.get("scheduled_time_utc"), "Channel": s.get("channel"),
                   "Region": s.get("region"), "Mode": s.get("mode"),
                   "Status": s.get("status")} for s in sc] or [{"When (UTC)": "—"}])

    # --- UTM ---
    with tabs[3]:
        st.subheader("UTM Generator")
        with st.form("utm", clear_on_submit=False):
            src = st.text_input("Source", value="x")
            med = st.text_input("Medium", value="social")
            camp = st.text_input("Campaign", value="realitycheck")
            cont = st.text_input("Content tag (optional)")
            if st.form_submit_button("Generate link", type="primary"):
                row = growth.make_utm(src, med, camp, cont)
                st.code(row["link"])
                st.success("Link generated & logged.")

    # --- Templates ---
    with tabs[4]:
        st.subheader("Content Templates")
        st.caption("On-brand, compliant starting points. Copy, customize, then add to the vault.")
        for k, val in growth.TEMPLATES.items():
            with st.expander(k):
                st.code(val)

    # --- Daily Plan ---
    with tabs[5]:
        st.subheader("Daily Attack Plan")
        if st.button("Generate today's plan", type="primary"):
            plan = growth.generate_daily_plan()
            st.success("Plan generated.")
        st.table([{"Task": t["task"], "Channel": t["channel"], "Count": t["count"]}
                  for t in growth.DAILY_PLAN_TEMPLATE])

    # --- Influencers ---
    with tabs[6]:
        st.subheader("Influencer DM Queue")
        st.caption("Drafts a queue. Sending is manual / official-API-later — never auto.")
        with st.form("inf", clear_on_submit=True):
            name = st.text_input("Name")
            plat = st.text_input("Platform", value="x")
            url = st.text_input("Profile URL")
            niche = st.text_input("Niche", value="trading")
            msg = st.text_area("Message", value=growth.TEMPLATES["influencer_dm"])
            if st.form_submit_button("Add to queue"):
                growth.add_influencer(name, plat, url, niche, msg)
                st.success("Added to queue.")
        infl = growth.list_influencers(limit=100)
        st.table([{"Name": i.get("name"), "Platform": i.get("platform"),
                   "Niche": i.get("niche"), "Status": i.get("status"),
                   "Reply": i.get("reply_status")} for i in infl] or [{"Name": "—"}])

    # --- Reddit Scout ---
    with tabs[7]:
        st.subheader("Reddit Scout")
        st.warning("Scout & draft only. This NEVER posts to Reddit. Approval required to act.")
        with st.form("rdt", clear_on_submit=True):
            sub = st.text_input("Subreddit", value="r/")
            idea = st.text_area("Post idea")
            draft = st.text_area("Reply draft")
            if st.form_submit_button("Save draft"):
                row = growth.add_reddit_scout(sub, idea, draft)
                st.success(f"Saved. Self-promo risk: {row['self_promo_risk']}.")
        sc = growth.list_reddit_scout(limit=100)
        st.table([{"Subreddit": s.get("subreddit"), "Risk": s.get("self_promo_risk"),
                   "Compliance": s.get("compliance_status"), "Status": s.get("status")}
                  for s in sc] or [{"Subreddit": "—"}])

    # --- Channels ---
    with tabs[8]:
        st.subheader("Channel Modes")
        st.caption("auto = official-API publish (mock until key present) · approval = human publishes · "
                   "scout = finds & drafts, never posts · locked = off.")
        st.table([{"Channel": c["label"], "Mode": c["mode"],
                   "API ready": "✓" if c["api_ready"] else "—",
                   "Publishes": c["publishes"]} for c in ov["channels"]])
        st.markdown("**Mock publish test** (approved content only)")
        approved = [i for i in growth.list_content(limit=500) if i.get("status") == "approved"]
        if approved:
            pick = st.selectbox("Approved content", [f"{i['title']} · {i['content_id']}" for i in approved], key="mock_pick")
            mch = st.selectbox("Channel", ["x", "instagram", "youtube"], key="mock_ch")
            if st.button("Mock publish"):
                cid = pick.split("·")[-1].strip()
                fn = {"x": growth.publish_x_mock, "instagram": growth.publish_instagram_mock,
                      "youtube": growth.publish_youtube_mock}[mch]
                res = fn(cid)
                if res["ok"]:
                    st.success(f"{res['mode']} publish OK → {res['post_url']}")
                else:
                    st.error(res["reason"])
        else:
            st.info("Approve content first to test mock publish.")
        st.markdown("**Publish log**")
        lg = growth.list_publish_log(limit=50)
        st.table([{"When": l.get("published_at"), "Channel": l.get("channel"),
                   "Action": l.get("action"), "URL": l.get("post_url")} for l in lg] or [{"When": "—"}])

    _back()
