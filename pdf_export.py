"""
pdf_export.py
-------------
Renders a full report dict into a downloadable PDF (reportlab).

Sections (per V1 spec): title, generated date + uploaded-file summary, pass
odds, killer rules, firm comparison, what-if table, expected fee burn, and a
clear 'not financial advice' note.
"""

from __future__ import annotations
import io
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, Image)

_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

INK = colors.HexColor("#1c1b17")
GREEN = colors.HexColor("#1d4634")
CLAY = colors.HexColor("#9c3b1d")
LINE = colors.HexColor("#ddd4c3")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("H1c", parent=ss["Title"], textColor=INK, fontSize=22,
                          spaceAfter=4))
    ss.add(ParagraphStyle("Sub", parent=ss["Normal"], textColor=CLAY, fontSize=9,
                          spaceAfter=14))
    ss.add(ParagraphStyle("H2c", parent=ss["Heading2"], textColor=GREEN, fontSize=13,
                          spaceBefore=12, spaceAfter=6))
    ss.add(ParagraphStyle("Body", parent=ss["Normal"], textColor=INK, fontSize=10,
                          leading=14))
    ss.add(ParagraphStyle("Small", parent=ss["Normal"], textColor=colors.grey,
                          fontSize=8, leading=11))
    ss.add(ParagraphStyle("Lantern", parent=ss["Normal"],
                          textColor=colors.HexColor("#D9A332"), fontSize=8,
                          leading=11, spaceAfter=8))
    return ss


def _pct(p):
    return f"{p * 100:.1f}%"


def _pct_range(p, n_trades=None):
    """Bayesian credible interval for pass-odds (Beta-Binomial, Jeffreys prior).
    Presentation only; engine value unchanged. Asymmetric and bounded in [0,1]."""
    import bayesian
    return bayesian.credible_interval_pct(p, n_trades, cred=0.80)


# ---------------------------------------------------------------------------
# Report polish helpers (presentation only — no engine logic)
# ---------------------------------------------------------------------------
GOLD = colors.HexColor("#D9A332")
CARD_BG = colors.HexColor("#13110c")
CARD_TEXT = colors.HexColor("#F7F3EA")

def _generic_ruleset_label(firm_name: str) -> str:
    """Public-safe generic label for the shareable card (no real firm names)."""
    n = (firm_name or "").lower()
    if "eod" in n or "apex" in n:
        return "EOD-style ruleset"
    if "one" in n and "step" in n or "1-step" in n or "e8" in n:
        return "One-step ruleset"
    if "2-step" in n or "two" in n:
        return "Two-step ruleset"
    if "stellar" in n:
        return "Two-step ruleset"
    if "stakes" in n or "5ers" in n:
        return "Two-step ruleset"
    return "Best matching ruleset"


def _share_card(ss, rows):
    """Build a screenshot-friendly summary card table. rows = list of (label, value)."""
    data = []
    for label, value in rows:
        data.append([Paragraph(f'<font color="#D9A332" size="7">{label}</font>',
                               ss["Small"]),
                     Paragraph(f'<font color="#F7F3EA" size="11"><b>{value}</b></font>',
                               ss["Body"])])
    t = Table(data, colWidths=[42 * mm, 116 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#2a261c")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 1, GOLD),
    ]))
    return t


def _glossary_block(ss, el):
    """Mini glossary — one line per term, presentation only."""
    el.append(Paragraph("Mini glossary", ss["H2c"]))
    terms = [
        ("Trailing drawdown", "A drawdown limit that can move as account equity rises."),
        ("EOD drawdown", "A drawdown calculation based on end-of-day equity rather than every intraday tick."),
        ("Daily loss limit", "The maximum loss allowed within a trading day under a ruleset."),
        ("Retry loop", "The repeated cost of buying or restarting challenges after failure."),
        ("Fee burn", "The estimated cost pressure created by low pass odds and repeated attempts."),
        ("Risk DNA", "Behavioral risk patterns detected from your uploaded history."),
        ("Killer rule", "The rule most often associated with failure in simulation."),
        ("Killer behavior", "The trading behavior most associated with drawdown pressure in your uploaded history."),
        ("Confidence", "A data-quality label based on trade count, trading days, and available fields."),
    ]
    for term, desc in terms:
        el.append(Paragraph(f"<b>{term}:</b> {desc}", ss["Small"]))


def _closing_bridge(ss, el, mode="prop"):
    """Closing bridge — what to do with this report. No advice language."""
    el.append(Paragraph("What to do with this report", ss["H2c"]))
    el.append(Paragraph(
        "This report is a snapshot of the uploaded history and the ruleset "
        "version shown above. If your risk settings, trade behavior, "
        "instrument mix, or a public ruleset changes, rerun the RealityCheck "
        "with updated data.", ss["Body"]))
    el.append(Paragraph("Common reasons to rerun:", ss["Body"]))
    for reason in ["You changed position sizing",
                   "You added 30+ new trades",
                   "You switched instruments",
                   "A public challenge rule changed",
                   "Your drawdown pattern changed"]:
        el.append(Paragraph(f"&bull; {reason}", ss["Body"]))
    el.append(Spacer(1, 4))
    el.append(Paragraph(
        "<b>Next steps:</b> Rerun after new data &nbsp;&middot;&nbsp; "
        "Compare another mode &nbsp;&middot;&nbsp; Submit your outcome later.",
        ss["Body"]))
    el.append(Paragraph(
        "Testing different risk settings? A 3-report bundle lets you compare "
        "scenarios without starting from scratch.", ss["Small"]))


def build_pdf(full_report: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            title="Prop Firm RealityCheck Report")
    ss = _styles()
    el = []
    _nt = (full_report.get("data") or {}).get("n_trades")  # for pass-odds confidence bands

    # Candor logo at the top (never break the PDF if the asset is missing)
    try:
        _lp = os.path.join(_ASSETS, "candor-logo-primary-light.png")
        if os.path.exists(_lp):
            from reportlab.lib.utils import ImageReader
            iw, ih = ImageReader(_lp).getSize()
            w = 52 * mm
            el.append(Image(_lp, width=w, height=w * ih / iw))
            el.append(Spacer(1, 6 * mm))
    except Exception:
        pass

    el.append(Paragraph("\u25C6 LANTERN SCAN COMPLETE", ss["Lantern"]))
    el.append(Paragraph("Prop Firm RealityCheck Report", ss["H1c"]))
    el.append(Paragraph("Generated from your trading history · Candor", ss["Sub"]))

    # --- Shareable score card (public-safe: generic ruleset labels only) ---
    _rows_sorted = sorted(full_report["firm_rows"], key=lambda r: r["pass_prob"], reverse=True)
    _best = _rows_sorted[0] if _rows_sorted else None
    if _best:
        _vlabel = {"go": "Strong fit", "wait": "Borderline", "skip": "High mismatch"}.get(_best["verdict"], "—")
        el.append(_share_card(ss, [
            ("CANDOR REALITYCHECK", "Prop Firm RealityCheck \u00b7 Lantern Scan Complete"),
            ("BEST MATCHING RULESET", f"{_generic_ruleset_label(_best['firm'])} \u00b7 {_pct_range(_best['pass_prob'], _nt)} \u00b7 {_vlabel}"),
            ("KILLER RULE", _best.get("killer_rule", "—")),
            ("CONFIDENCE", str(full_report.get("confidence", "—"))),
            ("REPORT ID", str(full_report.get("report_id", "—"))),
        ]))
        el.append(Spacer(1, 8))

    # --- Score context band ---
    el.append(Paragraph("How to read the risk labels", ss["H2c"]))
    el.append(Paragraph(
        "<b>Strong Fit:</b> this uploaded history showed stronger fit with "
        "this ruleset in simulation. &nbsp; <b>Borderline:</b> this uploaded "
        "history produced mixed results under this ruleset. &nbsp; "
        "<b>High Mismatch:</b> this uploaded history showed high mismatch or "
        "high retry-risk under this ruleset.", ss["Body"]))
    el.append(Paragraph(
        "Labels describe simulation behavior of the uploaded history only — "
        "not a forecast, not advice, not a guarantee.", ss["Small"]))

    d = full_report["data"]
    el.append(Paragraph("Your data", ss["H2c"]))
    el.append(Paragraph(
        f"Report ID: {full_report.get('report_id','-')}<br/>"
        f"Ruleset version: {full_report.get('ruleset_version','-')}<br/>"
        f"Simulation date: {full_report['generated']} &nbsp;·&nbsp; "
        f"Confidence: {full_report.get('confidence','-')}<br/>"
        f"Trades read: {d.get('n_trades')} &nbsp;·&nbsp; "
        f"Trading days: {d.get('n_days')} &nbsp;·&nbsp; "
        f"Profitable days: {d.get('profitable_days')}<br/>"
        f"Source: {d.get('source_hint')}", ss["Body"]))

    # firm comparison
    el.append(Paragraph("Firm comparison", ss["H2c"]))
    el.append(Paragraph(
        "Pass odds are shown as 80% confidence ranges, not single-point "
        f"precision. Ranges come from {_nt if _nt else 'the uploaded'} "
        "trades and narrow as you add more data.", ss["Small"]))
    rows = [["Firm", "Pass odds", "Risk label", "Killer rule", "Fee"]]
    for r in full_report["firm_rows"]:
        rows.append([r["firm"], _pct_range(r["pass_prob"], _nt), {"go":"Strong fit","wait":"Borderline","skip":"High mismatch"}.get(r["verdict"],"—"),
                     r["killer_rule"], f"${r['fee']:,}"])
    t = Table(rows, colWidths=[55 * mm, 18 * mm, 18 * mm, 50 * mm, 18 * mm])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f2ea")]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    el.append(t)

    # cross-firm leverage map
    lev = full_report.get("leverage_map", {})
    if lev and lev.get("headline"):
        el.append(Paragraph("Leverage Map - the one thing that opens the most doors", ss["H2c"]))
        if lev.get("firms_blocked_by_dominant", 0) >= 2:
            el.append(Paragraph(
                f"Dominant blocker: <b>{lev['dominant_blocker_label']}</b> "
                f"- blocks <b>{lev['firms_blocked_by_dominant']} of "
                f"{lev['total_firms']}</b> firms that challenge you.", ss["Body"]))
        el.append(Paragraph(lev["headline"], ss["Body"]))
        if lev.get("contradiction"):
            el.append(Paragraph(
                "&#9888; The simulation shows opposite failure modes across "
                "rulesets - they don't share a single fix.", ss["Body"]))
        el.append(Paragraph(lev["detail"], ss["Body"]))
        el.append(Paragraph(
            "Cross-firm leverage analysis from uploaded history. Diagnostic only.",
            ss["Small"]))

    # killer rule autopsy
    au = full_report.get("autopsy")
    if au:
        el.append(Paragraph(f"Killer Rule Autopsy — {au.get('rule','—')}", ss["H2c"]))
        el.append(Paragraph(au.get("mechanism", ""), ss["Body"]))
        if au.get("path"):
            el.append(Paragraph("<b>How it usually happens:</b> " +
                                " &rarr; ".join(au["path"]), ss["Body"]))
        if au.get("reduce"):
            el.append(Paragraph("<b>What the simulation is sensitive to:</b>", ss["Body"]))
        for x in au.get("reduce", []):
            el.append(Paragraph(f"• {x}", ss["Body"]))
        el.append(Paragraph(au.get("label", ""), ss["Small"]))

    # best-fit matchmaker
    mch = full_report.get("matchmaker")
    if mch:
        el.append(Paragraph("Historical ruleset fit", ss["H2c"]))
        el.append(Paragraph(f"<b>Highest historical fit — {mch['best_firm']}</b> ({_pct_range(mch['best_odds'], _nt)}): "
                            + "; ".join(mch["best_why"]), ss["Body"]))
        el.append(Paragraph(f"<b>Severe mismatch — {mch['worst_firm']}</b> ({_pct_range(mch['worst_odds'], _nt)}): "
                            + "; ".join(mch["worst_why"]), ss["Body"]))
        el.append(Paragraph(mch.get("label", ""), ss["Small"]))
    el.append(Paragraph("Expected fee burn", ss["H2c"]))
    _fb = full_report.get("fee_burn_headline", {})
    if _fb.get("note"):
        el.append(Paragraph(_fb["note"], ss["Small"]))
    for r in full_report["firm_rows"]:
        el.append(Paragraph(
            f"<b>{r['firm']}</b>: {r['fee_burn_msg']} "
            f"(retry danger: {r.get('retry_danger','-')})", ss["Body"]))

    # what-if
    wi = full_report["what_if"]
    el.append(Paragraph(f"What-if simulator — {wi['firm']}", ss["H2c"]))
    el.append(Paragraph(wi["label"], ss["Small"]))
    el.append(Spacer(1, 4))
    wrows = [["Risk level", "Estimated pass odds", "Killer rule"]]
    for row in wi["rows"]:
        wrows.append([f"{row['risk_pct']}%", _pct_range(row["pass_prob"], _nt), row["killer_rule_label"]])
    wt = Table(wrows, colWidths=[30 * mm, 45 * mm, 60 * mm])
    wt.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f2ea")]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    el.append(wt)

    # risk DNA
    dna = full_report.get("risk_dna", {})
    el.append(Paragraph("Your Risk DNA", ss["H2c"]))
    if dna.get("available"):
        m = dna["metrics"]
        el.append(Paragraph(
            f"<b>Most dangerous behavior:</b> {dna['most_dangerous_behavior']} — "
            f"{dna['behavior_note']}", ss["Body"]))
        el.append(Paragraph(
            f"Longest losing streak: {m['longest_loss_streak']} days "
            f"(sensitivity {m['loss_streak_sensitivity']}) &nbsp;·&nbsp; "
            f"Profit concentration: {m['concentration_label']} &nbsp;·&nbsp; "
            f"Risk drift: {m['drift_label']}", ss["Body"]))
        el.append(Paragraph(dna.get("label", ""), ss["Small"]))
    else:
        el.append(Paragraph(dna.get("note", "Not enough data for a behavioral read."), ss["Small"]))

    # kelly sizing
    kel = full_report.get("kelly", {})
    if kel and kel.get("headline"):
        el.append(Paragraph("Sizing Pressure - Kelly Lens", ss["H2c"]))
        el.append(Paragraph("Growth-optimal fraction estimate, not a live size recommendation.", ss["Small"]))
        pr = kel.get("payoff_ratio", 0)
        pr_str = "infinite" if pr == float("inf") else f"{pr:.2f}"
        el.append(Paragraph(
            f"Win rate: <b>{kel['win_rate']*100:.0f}%</b> &nbsp;·&nbsp; "
            f"Payoff ratio: <b>{pr_str}</b> &nbsp;·&nbsp; "
            f"Full Kelly: <b>{kel.get('kelly_fraction',0)*100:.0f}%</b> of bankroll per bet",
            ss["Body"]))
        el.append(Paragraph(kel["headline"], ss["Body"]))
        el.append(Paragraph(f"<b>Prudent range:</b> {kel['recommended_fraction_label']}", ss["Body"]))
        el.append(Paragraph(kel["detail"], ss["Body"]))
        if kel.get("sizing_note"):
            el.append(Paragraph(kel["sizing_note"], ss["Small"]))
        el.append(Paragraph(
            "Kelly analysis derived from uploaded history. Diagnostic only - not advice.",
            ss["Small"]))

    # regime analysis
    reg = full_report.get("regime", {})
    if reg:
        el.append(Paragraph("Regime & Volatility — is your history stable?", ss["H2c"]))
        rs = reg.get("regime_shift") or {}
        if rs:
            el.append(Paragraph(
                f"Early third: <b>${rs['early']['mean_pnl']:+,.0f}/day</b> "
                f"({rs['early']['win_rate']*100:.0f}% win) &nbsp;·&nbsp; "
                f"Middle: <b>${rs['middle']['mean_pnl']:+,.0f}/day</b> "
                f"({rs['middle']['win_rate']*100:.0f}% win) &nbsp;·&nbsp; "
                f"Recent: <b>${rs['recent']['mean_pnl']:+,.0f}/day</b> "
                f"({rs['recent']['win_rate']*100:.0f}% win)", ss["Body"]))
            el.append(Paragraph(rs.get("edge_label", ""), ss["Body"]))
        if reg.get("vol_clustering_label"):
            el.append(Paragraph(reg["vol_clustering_label"], ss["Body"]))
        rd = reg.get("risk_drift") or {}
        if rd.get("label"):
            el.append(Paragraph(rd["label"], ss["Body"]))
        el.append(Paragraph(
            f"<b>Regime trust: {reg.get('regime_trust','-')}</b> — "
            f"{reg.get('regime_trust_label','')}", ss["Body"]))
        el.append(Paragraph(
            "Regime analysis derived from uploaded history. Diagnostic only.",
            ss["Small"]))

    # rule interaction
    ri = full_report.get("rule_interaction", {})
    if ri and ri.get("compound_label"):
        el.append(Paragraph("Rule Interaction — how rules compound", ss["H2c"]))
        cpct = ri.get("compound_breach_pct", 0)
        spct = ri.get("solo_breach_pct", 0)
        el.append(Paragraph(
            f"<b>Compound failures</b> (2+ rules near-simultaneously): "
            f"<b>{cpct*100:.0f}%</b> &nbsp;·&nbsp; "
            f"Single-rule failures: <b>{spct*100:.0f}%</b>",
            ss["Body"]))
        el.append(Paragraph(ri["compound_label"], ss["Body"]))
        for trap in (ri.get("trap_labels") or []):
            el.append(Paragraph(f"&#9888; {trap}", ss["Body"]))
        if ri.get("active_rules"):
            el.append(Paragraph(
                "Active rules: " + " · ".join(ri["active_rules"]),
                ss["Small"]))
        el.append(Paragraph(
            "Rule-interaction analysis derived from uploaded history. "
            "Diagnostic only — not financial advice.", ss["Small"]))

    # sequence risk (path-dependency)
    seq = full_report.get("sequence_risk", {})
    stk = (seq or {}).get("streak", {})
    if seq and seq.get("label"):
        el.append(Paragraph("Sequence Risk — the order, not just the average", ss["H2c"]))
        el.append(Paragraph(
            f"Average pass across orderings: <b>{seq['pass_rate_shuffled']*100:.0f}%</b> "
            f"&nbsp;·&nbsp; unluckiest 25% of orderings: <b>{seq['worst_quartile_pass']*100:.0f}%</b> "
            f"&nbsp;·&nbsp; order sensitivity: <b>{seq['order_sensitivity']*100:.0f}%</b>",
            ss["Body"]))
        if stk.get("lag1_autocorr") is not None:
            el.append(Paragraph(
                f"Streakiness score: <b>{stk['lag1_autocorr']:+.2f}</b> &nbsp;·&nbsp; "
                f"longest observed runs: {stk['longest_win_streak']} up / "
                f"{stk['longest_loss_streak']} down.", ss["Body"]))
        el.append(Paragraph(seq["label"], ss["Body"]))
        el.append(Paragraph(
            "Same days, same totals — only the order changes. This isolates "
            "run-of-the-cards risk a single win-rate can't show. Diagnostic only.",
            ss["Small"]))

    # personal danger rules
    dr = full_report.get("danger_rules", {})
    if dr.get("rules"):
        el.append(Paragraph("Your personal danger rules", ss["H2c"]))
        for x in dr["rules"]:
            el.append(Paragraph(f"• {x}", ss["Body"]))
        el.append(Paragraph(dr.get("label", ""), ss["Small"]))

    # outcome submission (Honesty Ledger teaser — full surface comes in Wave 2)
    el.append(Paragraph("When your challenge ends", ss["H2c"]))
    el.append(Paragraph(
        f"Help Candor measure its own predictions: when this challenge resolves, "
        f"submit your real outcome (passed / failed / not attempted) quoting Report ID "
        f"<b>{full_report.get('report_id','-')}</b>. We publish calibration once enough "
        f"verified outcomes are in — we don't hide from our predictions.", ss["Body"]))

    # --- Closing bridge ---
    _closing_bridge(ss, el, mode="prop")

    # --- Mini glossary ---
    _glossary_block(ss, el)

    el.append(Spacer(1, 16))
    el.append(Paragraph("Honesty &amp; disclaimer", ss["H2c"]))
    el.append(Paragraph(full_report["disclaimer"], ss["Small"]))
    el.append(Paragraph(
        "Some rulesets are seed data pending verification, and trailing/intraday "
        "drawdown is approximated from end-of-day balances. These limits are "
        "intentional and disclosed, not hidden.", ss["Small"]))

    doc.build(el)
    return buf.getvalue()

# ============================================================================
# Own Account RealityCheck — PDF builder
# ============================================================================
def _band_color(band: str):
    """Color hint for band labels (no false precision implied)."""
    return {
        "Low": GREEN,
        "Medium": colors.HexColor("#8a6d1c"),
        "High": CLAY,
        "Severe": colors.HexColor("#7a1d0d"),
        "Limited": colors.grey,
    }.get(band, INK)


def build_own_account_pdf(rep: dict) -> bytes:
    """Render an Own Account RealityCheck report dict into a PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            title=f"Candor — Own Account RealityCheck "
                                  f"{rep.get('report_id','')}")
    ss = _styles()
    el = []

    # logo
    logo = os.path.join(_ASSETS, "candor-logo-primary-dark.png")
    if os.path.exists(logo):
        el.append(Image(logo, width=70 * mm, height=18 * mm))
        el.append(Spacer(1, 6))

    el.append(Paragraph("\u25C6 LANTERN SCAN COMPLETE", ss["Lantern"]))
    el.append(Paragraph("Own Account RealityCheck", ss["H1c"]))
    el.append(Paragraph(
        f"Report {rep.get('report_id','')} &middot; Generated "
        f"{rep.get('generated','')} &middot; Confidence: "
        f"{rep.get('confidence','—')}", ss["Sub"]))

    # --- Shareable score card ---
    _sc = rep.get("survival_score") or {}
    _bd = rep.get("drawdown_bands") or {}
    _kb0 = rep.get("killer_behavior") or {}
    _score_v = _sc.get("score")
    el.append(_share_card(ss, [
        ("CANDOR REALITYCHECK", "Own Account RealityCheck \u00b7 Lantern Scan Complete"),
        ("ACCOUNT SURVIVAL SCORE", f"{_score_v if _score_v is not None else '—'} / 100"),
        ("OBSERVED DRAWDOWN BAND", str(_bd.get("observed_max_dd_band", "—"))),
        ("KILLER BEHAVIOR", str(_kb0.get("behavior", "—")) if _kb0.get("available") else "—"),
        ("CONFIDENCE", str(_sc.get("confidence", rep.get("confidence", "Limited")))),
        ("REPORT ID", str(rep.get("report_id", "—"))),
    ]))
    el.append(Spacer(1, 8))

    # --- Score context band ---
    el.append(Paragraph("How to read the score", ss["H2c"]))
    el.append(Paragraph(
        "<b>0\u201340:</b> high breakage pressure observed in this uploaded "
        "history. &nbsp; <b>40\u201365:</b> borderline resilience \u2014 risk "
        "patterns are present but not extreme. &nbsp; <b>65\u2013100:</b> "
        "stronger historical resilience, subject to data confidence.",
        ss["Body"]))
    el.append(Paragraph(
        "The score describes the uploaded history only \u2014 not a forecast, "
        "not advice, not a guarantee.", ss["Small"]))

    # Executive summary block
    ss_score = rep.get("survival_score") or {}
    bands = rep.get("drawdown_bands") or {}
    score_val = ss_score.get("score")
    score_str = "—" if score_val is None else str(score_val)
    obs_band = bands.get("observed_max_dd_band", "—")
    el.append(Paragraph("Executive summary", ss["H2c"]))
    el.append(Paragraph(
        f"<b>Account Survival Score:</b> {score_str} / 100 &nbsp;&middot;&nbsp; "
        f"<b>Observed drawdown band:</b> {obs_band} &nbsp;&middot;&nbsp; "
        f"<b>Confidence:</b> {ss_score.get('confidence','Limited')}", ss["Body"]))
    el.append(Paragraph(
        "Statistical risk diagnostics only. Estimated from uploaded history; "
        "not a forecast. Not trading advice.", ss["Small"]))
    el.append(Spacer(1, 6))

    # Account inputs
    acc = rep.get("account") or {}
    el.append(Paragraph("Account inputs", ss["H2c"]))
    el.append(Paragraph(
        f"Starting balance: {acc.get('currency','USD')} "
        f"{acc.get('starting_balance', 0):,.0f} &nbsp;&middot;&nbsp; "
        f"Leverage: {acc.get('leverage', 0):g}x &nbsp;&middot;&nbsp; "
        f"Stop-out: {acc.get('stop_out_pct') or 50}%", ss["Body"]))

    # Data quality
    audit = rep.get("data_audit") or {}
    el.append(Paragraph("Data quality", ss["H2c"]))
    el.append(Paragraph(
        f"Trades: {audit.get('n_trades','—')} &nbsp;&middot;&nbsp; "
        f"Trading days: {audit.get('n_days','—')} &nbsp;&middot;&nbsp; "
        f"Profitable days: {audit.get('profitable_days','—')} &nbsp;&middot;&nbsp; "
        f"Outliers: {audit.get('outliers','—')}", ss["Body"]))
    if audit.get("confidence_why"):
        el.append(Paragraph(audit["confidence_why"], ss["Small"]))

    # Drawdown risk bands table
    el.append(Paragraph("Drawdown risk bands", ss["H2c"]))
    rows = [["Threshold", "Sensitivity band", "Breached in history?"]]
    for r in bands.get("rows", []):
        rows.append([
            f"{r['threshold_pct']}%",
            r["band"],
            "Yes" if r["breached_in_history"] else "No",
        ])
    t = Table(rows, hAlign="LEFT", colWidths=[35 * mm, 50 * mm, 50 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5efe2")),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    el.append(t)
    el.append(Paragraph(
        "Bands are coarse on purpose to avoid false precision. "
        "Estimated from uploaded history; not a forecast.", ss["Small"]))

    # Killer behavior
    kb = rep.get("killer_behavior") or {}
    el.append(Paragraph("Killer behavior", ss["H2c"]))
    if kb.get("available"):
        el.append(Paragraph(
            f"<b>Most dangerous behavior:</b> {kb.get('behavior','—')}", ss["Body"]))
        el.append(Paragraph(kb.get("note", ""), ss["Body"]))
        m = kb.get("metrics", {})
        el.append(Paragraph(
            f"Longest losing streak: {m.get('longest_loss_streak','—')} days "
            f"&middot; Sensitivity: {m.get('loss_streak_sensitivity','—')} "
            f"&middot; Profit concentration: {m.get('concentration_label','—')} "
            f"&middot; Risk drift: {m.get('drift_label','—')}", ss["Small"]))
    else:
        el.append(Paragraph(kb.get("note",
                            "Not enough data for a behavioral read."),
                            ss["Body"]))

    # Margin pressure
    mp = rep.get("margin_pressure") or {}
    el.append(Paragraph("Margin pressure", ss["H2c"]))
    if mp.get("available"):
        el.append(Paragraph(
            f"Observed equity floor (worst-case in sample): "
            f"<b>{mp.get('observed_floor_pct')}%</b> of starting balance. "
            f"Margin pressure band: <b>{mp.get('margin_pressure_band')}</b>. "
            f"Headroom vs {mp.get('stop_out_pct')}% stop-out: "
            f"<b>{mp.get('stopout_headroom_band')}</b>.",
            ss["Body"]))
        el.append(Paragraph(
            "Estimated from uploaded history; not a forecast.", ss["Small"]))
    else:
        el.append(Paragraph(mp.get("note", ""), ss["Body"]))

    # What-if
    wif = rep.get("what_if") or {}
    el.append(Paragraph("What-if lab", ss["H2c"]))
    rows = [["Historical risk scaled to", "Observed drawdown band"]]
    for r in wif.get("rows", []):
        rows.append([f"{r['risk_pct']}%", r["observed_dd_band"]])
    t = Table(rows, hAlign="LEFT", colWidths=[60 * mm, 60 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5efe2")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, LINE),
    ]))
    el.append(t)
    el.append(Paragraph(wif.get("label", ""), ss["Small"]))

    # Instrument & session (V0: graceful unavailable)
    el.append(Paragraph("Instrument fit", ss["H2c"]))
    el.append(Paragraph(rep.get("instrument_fit", {}).get("note", ""),
                        ss["Body"]))
    el.append(Paragraph("Session risk", ss["H2c"]))
    el.append(Paragraph(rep.get("session_risk", {}).get("note", ""),
                        ss["Body"]))

    # Checklist
    chk = rep.get("checklist") or {}
    el.append(Paragraph("Personal risk-control checklist", ss["H2c"]))
    for it in chk.get("items", []):
        el.append(Paragraph(f"&bull; {it}", ss["Body"]))
    el.append(Paragraph(chk.get("label", ""), ss["Small"]))

    # --- Closing bridge ---
    _closing_bridge(ss, el, mode="own")

    # --- Mini glossary ---
    _glossary_block(ss, el)

    # Disclaimer footer
    el.append(Spacer(1, 10))
    el.append(Paragraph(rep.get("disclaimer", ""), ss["Small"]))
    el.append(Paragraph(
        "We do not tell you what to buy, sell, trade, enter, avoid, or "
        "attempt. We show statistical estimates and risk patterns based on "
        "the data you uploaded.", ss["Small"]))

    doc.build(el)
    return buf.getvalue()
