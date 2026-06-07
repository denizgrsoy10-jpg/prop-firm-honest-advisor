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
    return ss


def _pct(p):
    return f"{p * 100:.1f}%"


def build_pdf(full_report: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            title="Prop Firm RealityCheck Report")
    ss = _styles()
    el = []

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

    el.append(Paragraph("Prop Firm RealityCheck Report", ss["H1c"]))
    el.append(Paragraph("Generated from your trading history · Candor", ss["Sub"]))

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
    rows = [["Firm", "Pass odds", "Risk label", "Killer rule", "Fee"]]
    for r in full_report["firm_rows"]:
        rows.append([r["firm"], _pct(r["pass_prob"]), {"go":"Strong fit","wait":"Borderline","skip":"High mismatch"}.get(r["verdict"],"—"),
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

    # killer rule autopsy
    au = full_report.get("autopsy")
    if au:
        el.append(Paragraph(f"Killer Rule Autopsy — {au.get('rule','—')}", ss["H2c"]))
        el.append(Paragraph(au.get("mechanism", ""), ss["Body"]))
        if au.get("path"):
            el.append(Paragraph("<b>How it usually happens:</b> " +
                                " &rarr; ".join(au["path"]), ss["Body"]))
        for x in au.get("reduce", []):
            el.append(Paragraph(f"• {x}", ss["Body"]))
        el.append(Paragraph(au.get("label", ""), ss["Small"]))

    # best-fit matchmaker
    mch = full_report.get("matchmaker")
    if mch:
        el.append(Paragraph("Best-fit challenge type", ss["H2c"]))
        el.append(Paragraph(f"<b>Best fit — {mch['best_firm']}</b> ({_pct(mch['best_odds'])}): "
                            + "; ".join(mch["best_why"]), ss["Body"]))
        el.append(Paragraph(f"<b>Lowest fit — {mch['worst_firm']}</b> ({_pct(mch['worst_odds'])}): "
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
        wrows.append([f"{row['risk_pct']}%", _pct(row["pass_prob"]), row["killer_rule_label"]])
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

    el.append(Spacer(1, 16))
    el.append(Paragraph("Honesty &amp; disclaimer", ss["H2c"]))
    el.append(Paragraph(full_report["disclaimer"], ss["Small"]))
    el.append(Paragraph(
        "Some rulesets are seed data pending verification, and trailing/intraday "
        "drawdown is approximated from end-of-day balances. These limits are "
        "intentional and disclosed, not hidden.", ss["Small"]))

    doc.build(el)
    return buf.getvalue()
