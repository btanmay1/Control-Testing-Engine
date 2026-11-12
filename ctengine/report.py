"""Auto-generated Excel workbook and PDF summary of the control testing results."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.dataframe import dataframe_to_rows
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF")
THIN = Side(style="thin", color="BFBFBF")
RATING_FILLS = {"Effective": "C6EFCE", "Partially Effective": "FFEB9C", "Needs Improvement": "FFEB9C", "Ineffective": "FFC7CE"}


def _write_sheet(wb: Workbook, title: str, df: pd.DataFrame, note: str | None = None) -> None:
    ws = wb.create_sheet(title)
    start = 1
    if note:
        ws.cell(row=1, column=1, value=note).font = Font(italic=True, color="595959")
        start = 3
    for r_i, row in enumerate(dataframe_to_rows(df, index=False, header=True), start=start):
        for c_i, val in enumerate(row, start=1):
            cell = ws.cell(row=r_i, column=c_i, value=val)
            cell.border = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
            if r_i == start:
                cell.fill, cell.font = HEADER_FILL, HEADER_FONT
                cell.alignment = Alignment(wrap_text=True, vertical="center")
    for c_i, col in enumerate(df.columns, start=1):
        width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) + 2
        ws.column_dimensions[get_column_letter(c_i)].width = min(max(width, 10), 60)
    ws.freeze_panes = ws.cell(row=start + 1, column=1)
    if len(df):
        ws.auto_filter.ref = f"A{start}:{get_column_letter(len(df.columns))}{start + len(df)}"
    # colour any rating columns
    for c_i, col in enumerate(df.columns, start=1):
        if "verdict" in col.lower() or "rating" in col.lower() or col == "Operating effectiveness":
            letter = get_column_letter(c_i)
            for text, color in RATING_FILLS.items():
                ws.conditional_formatting.add(f"{letter}{start + 1}:{letter}{start + len(df)}",
                                              CellIsRule(operator="equal", formula=[f'"{text}"'], fill=PatternFill("solid", fgColor=color)))


def write_excel(path: Path, summary: pd.DataFrame, exceptions: pd.DataFrame, samples: pd.DataFrame,
                validation: pd.DataFrame, quarantine: pd.DataFrame, reconciliation: pd.DataFrame, meta: dict) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    _write_sheet(wb, "Summary", summary, note=f"Control testing results | Period {meta['period']} | Generated {meta['generated']}")
    _write_sheet(wb, "Exception Log", exceptions, note="Full-population exceptions with evidence. One row per control exception.")
    _write_sheet(wb, "Sample Testing", samples, note="Sampled items, selection method and test result per item.")
    _write_sheet(wb, "Data Validation", validation, note=f"Records in: {meta['records_in']:,} | Passed: {meta['records_clean']:,} | Quarantined: {meta['records_quarantined']:,}")
    _write_sheet(wb, "Quarantine", quarantine, note="Records excluded from testing and the reason for exclusion.")
    _write_sheet(wb, "Reconciliation", reconciliation, note="SQL result vs independent Pandas re-performance, and vs planted ground truth.")
    method = pd.DataFrame({"Step": [
        "1. Data validation", "2. Full-population testing", "3. Re-performance", "4. Sampling",
        "5. Design effectiveness", "6. Operating effectiveness", "7. Control rating"], "Approach": [
        "Completeness, validity and uniqueness checks; failing records quarantined with reasons; record counts reconciled.",
        "Each control tested on 100% of its in-scope population using SQL (sql/control_tests.sql).",
        "Every SQL test independently re-performed in Pandas; any mismatch fails the run.",
        f"Random (n={meta['sample_size']}), stratified by amount band (n={meta['sample_size']}) and judgmental risk-based (n={meta['sample_size'] // 2}) samples per control.",
        "Control attributes assessed: owner, documented procedure, defined threshold, evidence retained, addresses the risk, timeliness.",
        f"Effective if sample deviations <= {meta['allowable']} and population exception rate <= {meta['tolerable']:.1%}; Needs Improvement up to 2x tolerance; otherwise Ineffective.",
        "Effective only if design and operation are both effective; Ineffective if either is ineffective; otherwise Partially Effective."]})
    _write_sheet(wb, "Methodology", method)
    wb.save(path)


def write_pdf(path: Path, summary: pd.DataFrame, top_exceptions: pd.DataFrame, meta: dict) -> None:
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=8, leading=10)
    hdr = small.clone("hdr", textColor=colors.white, fontName="Helvetica-Bold")
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title="Control Testing Report")
    story = [Paragraph("Card Transaction Controls - Automated Testing Report", styles["Title"]),
             Paragraph(f"Test period: {meta['period']} &nbsp;|&nbsp; Records in: {meta['records_in']:,} &nbsp;|&nbsp; "
                       f"Tested: {meta['records_clean']:,} &nbsp;|&nbsp; Quarantined: {meta['records_quarantined']:,} "
                       f"&nbsp;|&nbsp; Generated: {meta['generated']}", styles["BodyText"]),
             Spacer(1, 6 * mm), Paragraph("Control results", styles["Heading2"])]

    cols = ["Control ID", "Control", "Population", "Exceptions", "Exception rate", "Sample size",
            "Sample deviations", "Design effectiveness", "Operating effectiveness", "Control rating"]
    data = [[Paragraph(c, hdr) for c in cols]]
    for _, r in summary.iterrows():
        data.append([Paragraph(str(r[c]), small) for c in cols])
    t = Table(data, repeatRows=1, colWidths=[18 * mm, 60 * mm, 22 * mm, 22 * mm, 22 * mm, 18 * mm, 20 * mm, 30 * mm, 30 * mm, 28 * mm])
    style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    for i, (_, r) in enumerate(summary.iterrows(), start=1):
        style.append(("BACKGROUND", (9, i), (9, i), colors.HexColor("#" + RATING_FILLS.get(r["Control rating"], "FFFFFF"))))
    t.setStyle(TableStyle(style))
    story += [t, Spacer(1, 6 * mm), Paragraph("Design gaps and observations", styles["Heading2"])]
    for _, r in summary.iterrows():
        story.append(Paragraph(f"<b>{r['Control ID']}</b>: design gaps - {r['Design gaps']}. {r['Observation']}", small))

    story += [Spacer(1, 6 * mm), Paragraph("Largest exceptions by amount (top 15)", styles["Heading2"])]
    ecols = ["control_id", "txn_id", "card_id", "amount", "txn_timestamp", "exception_detail"]
    edata = [[Paragraph(c, hdr) for c in ecols]] + [[Paragraph(str(v), small) for v in row] for row in top_exceptions[ecols].values]
    et = Table(edata, repeatRows=1, colWidths=[22 * mm, 28 * mm, 28 * mm, 28 * mm, 38 * mm, 120 * mm])
    et.setStyle(TableStyle(style[:4]))
    story.append(et)
    doc.build(story)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
