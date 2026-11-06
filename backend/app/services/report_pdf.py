"""PDF rendering for reports, using ReportLab. It draws real charts from the stored chart data."""
from __future__ import annotations

import io
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = colors.HexColor("#0B1220")
BLUE = colors.HexColor("#2563EB")
INK = colors.HexColor("#1E293B")
MUTED = colors.HexColor("#64748B")
RULE = colors.HexColor("#CBD5E1")
BAND = colors.HexColor("#F1F5F9")
AMBER = colors.HexColor("#92400E")
SERIES = [colors.HexColor(c) for c in ("#2563EB", "#0891B2", "#7C3AED", "#D97706", "#DB2777", "#059669", "#475569", "#B91C1C")]
PAGE_WIDTH = A4[0] - 36 * mm

BODY = ParagraphStyle("Body", fontName="Helvetica", fontSize=9.5, leading=14, textColor=INK, spaceAfter=5)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=8, leading=11, textColor=MUTED)
H1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=NAVY, spaceBefore=12, spaceAfter=6)
H2 = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=NAVY, spaceBefore=8, spaceAfter=4)
TITLE = ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=20, leading=25, textColor=NAVY, spaceAfter=6, alignment=TA_LEFT)
BULLET = ParagraphStyle("Bullet", parent=BODY, leftIndent=10, bulletIndent=0)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=7.5, leading=9.5, spaceAfter=0)
HEAD = ParagraphStyle("Head", parent=CELL, fontName="Helvetica-Bold", textColor=colors.white)
NOTICE = ParagraphStyle("Notice", parent=BODY, textColor=AMBER, fontName="Helvetica-Bold", fontSize=9)

REPLACEMENTS = {"≥": ">=", "≤": "<=", "≠": "!=", "x": "x", "->": "->", "−": "-"}


def _clean(text) -> str:
    value = "" if text is None else str(text)
    for source, target in REPLACEMENTS.items():
        value = value.replace(source, target)
    # Helvetica uses Latin-1 encoding; other characters are replaced rather than drawn as boxes.
    return escape(value.encode("cp1252", "replace").decode("cp1252"))


def _value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:,.2f}" if abs(value) >= 1 else f"{value:.4g}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def _table(table: dict) -> Table:
    columns = table["columns"][:8]
    header = [Paragraph(_clean(str(c).replace("_", " ")), HEAD) for c in columns]
    rows = [[Paragraph(_clean(_value(row.get(c)))[:400], CELL) for c in columns] for row in table["rows"][:40]]
    width = PAGE_WIDTH / max(1, len(columns))
    result = Table([header, *rows], colWidths=[width] * len(columns), repeatRows=1)
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return result


def _numeric(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _chart(chart: dict) -> Drawing | None:
    rows = chart.get("rows") or []
    series = (chart.get("series") or [])[:6]
    if not rows or not series or chart.get("chart_type") in {"scatter", "box"}:
        return None
    width, height = PAGE_WIDTH, 62 * mm
    drawing = Drawing(width, height)
    drawing.add(String(0, height - 10, _plain(chart.get("title", ""))[:90], fontName="Helvetica-Bold", fontSize=9, fillColor=NAVY))
    labels = [str(r.get("x", "")) for r in rows]
    if chart.get("chart_type") in {"line", "area"} and len(rows) > 1:
        plot = LinePlot()
        plot.x, plot.y, plot.width, plot.height = 42, 28, width - 56, height - 56
        plot.data = [[(i, _numeric(r.get(s)) if _numeric(r.get(s)) is not None else 0.0) for i, r in enumerate(rows)] for s in series]
        for index, _ in enumerate(series):
            plot.lines[index].strokeColor = SERIES[index % len(SERIES)]
            plot.lines[index].strokeWidth = 1.4
        plot.xValueAxis.valueMin = 0
        plot.xValueAxis.valueMax = len(rows) - 1
        step = max(1, len(rows) // 8)
        plot.xValueAxis.valueSteps = list(range(0, len(rows), step))
        plot.xValueAxis.labelTextFormat = lambda v: labels[int(v)][:10] if 0 <= int(v) < len(labels) else ""
        plot.xValueAxis.labels.fontSize = 6.5
        plot.yValueAxis.labels.fontSize = 6.5
        plot.yValueAxis.labelTextFormat = _axis_label
        plot.yValueAxis.gridStrokeColor = RULE
        plot.yValueAxis.gridStrokeWidth = 0.25
        plot.yValueAxis.visibleGrid = True
        drawing.add(plot)
    else:
        shown = rows[:20]
        bars = VerticalBarChart()
        bars.x, bars.y, bars.width, bars.height = 42, 34, width - 56, height - 62
        bars.data = [[_numeric(r.get(s)) or 0 for r in shown] for s in series]
        bars.categoryAxis.categoryNames = [str(r.get("x", ""))[:14] for r in shown]
        bars.categoryAxis.labels.fontSize = 6.5
        bars.categoryAxis.labels.angle = 30 if len(shown) > 6 else 0
        bars.categoryAxis.labels.boxAnchor = "ne" if len(shown) > 6 else "n"
        bars.valueAxis.labels.fontSize = 6.5
        bars.valueAxis.labelTextFormat = _axis_label
        bars.valueAxis.gridStrokeColor = RULE
        bars.valueAxis.gridStrokeWidth = 0.25
        bars.valueAxis.visibleGrid = True
        for index, _ in enumerate(series):
            bars.bars[index].fillColor = SERIES[index % len(SERIES)]
            bars.bars[index].strokeColor = None
        drawing.add(bars)
    if len(series) > 1:
        legend = Legend()
        legend.x, legend.y = 42, height - 16
        legend.alignment = "right"
        legend.columnMaximum = 1
        legend.fontSize = 7
        legend.dx = legend.dy = 6
        legend.deltax = 62
        legend.colorNamePairs = [(SERIES[i % len(SERIES)], _plain(s)[:16]) for i, s in enumerate(series)]
        drawing.add(legend)
    return drawing


def _plain(text) -> str:
    return str(text).encode("cp1252", "replace").decode("cp1252")


def _axis_label(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if magnitude >= 1000:
        return f"{value / 1000:.0f}k"
    return f"{value:g}"


def render_pdf(content: dict) -> bytes:
    buffer = io.BytesIO()
    title = _plain(content["title"])

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"DataForge AI  |  {title[:80]}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {document.page}")
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(18 * mm, 14 * mm, A4[0] - 18 * mm, 14 * mm)
        canvas.restoreState()

    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
                                 title=title, author="DataForge AI", subject=content["report_type_label"])
    flow: list = []
    generated = datetime.fromisoformat(content["generated_at"]).strftime("%d %B %Y, %H:%M UTC")
    flow.append(Paragraph("DATAFORGE AI", ParagraphStyle("Brand", parent=SMALL, fontName="Helvetica-Bold", textColor=BLUE, spaceAfter=10)))
    flow.append(Paragraph(_clean(content["title"]), TITLE))
    meta = [["Report type", content["report_type_label"]], ["Workspace", content["workspace"]], ["Dataset", f"{content['dataset']} (version {content['version']})"], ["Generated", generated]]
    meta_table = Table([[Paragraph(f"<b>{_clean(a)}</b>", CELL), Paragraph(_clean(b), CELL)] for a, b in meta], colWidths=[30 * mm, PAGE_WIDTH - 30 * mm])
    meta_table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    flow.extend([meta_table, Spacer(1, 6)])
    if content.get("is_demo"):
        flow.append(Paragraph("Synthetic demonstration data. This report does not describe a real business.", NOTICE))

    flow.append(Paragraph("Executive summary", H1))
    flow.extend(Paragraph(_clean(item), BULLET, bulletText="•") for item in content["executive_summary"])

    overview = content["overview"]
    flow.append(Paragraph("Dataset overview", H1))
    flow.append(_table({"columns": ["Rows", "Columns", "Missing cells %", "Duplicate rows", "Quality score"],
                        "rows": [{"Rows": overview["rows"], "Columns": overview["columns"], "Missing cells %": overview["missing_pct"], "Duplicate rows": overview["duplicate_rows"], "Quality score": overview["quality_score"]}]}))

    flow.append(Paragraph("Analysis methodology", H1))
    flow.extend(Paragraph(_clean(item), BULLET, bulletText="•") for item in content["methodology"])

    if content["sections"]:
        flow.append(PageBreak())
        flow.append(Paragraph("Key findings", H1))
    for section in content["sections"]:
        block = [Paragraph(_clean(section["heading"]), H2)]
        if section.get("text"):
            block.append(Paragraph(_clean(section["text"]), BODY))
        chart = _chart(section["chart"]) if section.get("chart") else None
        if chart:
            block.extend([chart, Spacer(1, 4)])
        flow.append(KeepTogether(block))
        flow.extend(Paragraph(_clean(item), BULLET, bulletText="•") for item in section.get("findings", []))
        if section.get("table") and section["table"].get("rows"):
            flow.append(Spacer(1, 3))
            flow.append(_table(section["table"]))
            hidden = len(section["table"]["columns"]) - 8
            if hidden > 0 or len(section["table"]["rows"]) > 40:
                flow.append(Paragraph("The table is shortened here. The CSV and XLSX exports include every stored row and column.", SMALL))
        flow.append(Spacer(1, 6))

    flow.append(Paragraph("Recommendations", H1))
    if content["recommendations"]:
        flow.extend(Paragraph(_clean(item), BULLET, bulletText="•") for item in content["recommendations"])
    else:
        flow.append(Paragraph("No specific actions follow from these results.", BODY))
    flow.append(Paragraph("Limitations", H1))
    flow.extend(Paragraph(_clean(item), BULLET, bulletText="•") for item in content["limitations"])
    flow.append(Spacer(1, 6))
    flow.append(Paragraph("DataForge AI supports analysis. Review its assumptions and verify important decisions independently.", SMALL))
    document.build(flow, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
