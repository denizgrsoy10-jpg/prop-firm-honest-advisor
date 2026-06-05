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

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle)

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

    el.append(Paragraph("Prop Firm RealityCheck Report", ss["H1c"]))
    el.append(Paragraph("Generated from your trading history · Candor", ss["Sub"]))

    d = full_report["data"]
    el.append(Paragraph("Your data", ss["H2c"]))
    el.append(Paragraph(
        f"Simulation date: {full_report['generated']}<br/>"
        f"Trades read: {d.get('n_trades')} &nbsp;·&nbsp; "
        f"Trading days: {d.get('n_days')} &nbsp;·&nbsp; "
        f"Profitable days: {d.get('profitable_days')}<br/>"
        f"Source: {d.get('source_hint')}", ss["Body"]))

    # firm comparison
    el.append(Paragraph("Firm comparison", ss["H2c"]))
    rows = [["Firm", "Pass odds", "Verdict", "Killer rule", "Fee"]]
    for r in full_report["firm_rows"]:
        rows.append([r["firm"], _pct(r["pass_prob"]), r["verdict"].upper(),
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

    # expected fee burn
    el.append(Paragraph("Expected fee burn", ss["H2c"]))
    for r in full_report["firm_rows"]:
        el.append(Paragraph(f"<b>{r['firm']}</b>: {r['fee_burn_msg']}", ss["Body"]))

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

    el.append(Spacer(1, 16))
    el.append(Paragraph("Honesty &amp; disclaimer", ss["H2c"]))
    el.append(Paragraph(full_report["disclaimer"], ss["Small"]))
    el.append(Paragraph(
        "Some rulesets are seed data pending verification, and trailing/intraday "
        "drawdown is approximated from end-of-day balances. These limits are "
        "intentional and disclosed, not hidden.", ss["Small"]))

    doc.build(el)
    return buf.getvalue()
