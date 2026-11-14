"""Create a shareable PDF summary from a calculated retirement projection."""

from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from config import DISCLAIMER, FINANCIAL_YEAR, Assumptions, CLOSE_RATIO
from engine.projection import Household, SustainableIncome


GREEN = colors.HexColor("#24756B")
INK = colors.HexColor("#233B38")
MUTED = colors.HexColor("#60716E")
PALE = colors.HexColor("#F2F6F5")
GRID = colors.HexColor("#D7E1DE")


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _age_range(h: Household) -> str:
    if h.partner_age is None:
        retirement = "already retired" if h.already_retired else f"retires at {h.retirement_age}"
        return f"Age {h.age}; {retirement}"
    primary = "already retired" if h.already_retired else f"retires at {h.retirement_age}"
    partner = "already retired" if h.partner_already_retired else f"retires at {h.partner_retirement_age}"
    return f"You: age {h.age}, {primary}; partner: age {h.partner_age}, {partner}"


def _status(sustainable: SustainableIncome, goal: float, first_gap: int | None) -> tuple[str, colors.Color]:
    if not sustainable.feasible:
        return "Gap: costs cannot be funded", colors.HexColor("#A33A3A")
    ratio = sustainable.annual_income / goal if goal else 1.0
    if ratio >= 1 and first_gap is None:
        return "On track", GREEN
    if ratio >= CLOSE_RATIO:
        return "Close to goal", colors.HexColor("#A56717")
    return "Below goal", colors.HexColor("#A33A3A")


def build_results_pdf(
    h: Household,
    assumptions: Assumptions,
    projection: pd.DataFrame,
    sustainable: SustainableIncome,
    first_gap: int | None,
) -> bytes:
    """Return a self-contained PDF report of the current household estimate."""
    buffer = BytesIO()
    page_size = landscape(A4)
    doc = SimpleDocTemplate(
        buffer, pagesize=page_size, rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=17 * mm, bottomMargin=18 * mm, title="Retirement projection",
        author="Retirement planner",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=22, leading=27, textColor=INK, alignment=TA_LEFT,
        spaceAfter=3 * mm,
    ))
    styles.add(ParagraphStyle(
        name="ReportSubtitle", parent=styles["Normal"], fontSize=9,
        leading=13, textColor=MUTED, spaceAfter=5 * mm,
    ))
    styles.add(ParagraphStyle(
        name="Section", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=12, leading=15, textColor=GREEN, spaceBefore=5 * mm,
        spaceAfter=2 * mm,
    ))
    styles.add(ParagraphStyle(
        name="Small", parent=styles["Normal"], fontSize=7.5, leading=10,
        textColor=MUTED,
    ))
    styles.add(ParagraphStyle(
        name="Cell", parent=styles["Normal"], fontSize=7, leading=9,
        textColor=INK,
    ))

    def footer(canvas, document) -> None:
        canvas.saveState()
        canvas.setStrokeColor(GRID)
        canvas.line(15 * mm, 13 * mm, page_size[0] - 15 * mm, 13 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, 8 * mm, "General information only - not financial advice")
        canvas.drawRightString(page_size[0] - 15 * mm, 8 * mm, f"Page {document.page}")
        canvas.restoreState()

    story = [
        Paragraph("Your retirement projection", styles["ReportTitle"]),
        Paragraph(
            f"Prepared {date.today():%d %B %Y} · Model year {FINANCIAL_YEAR} · "
            "All amounts in Australian dollars and today's buying power",
            styles["ReportSubtitle"],
        ),
    ]

    status_text, status_color = _status(sustainable, h.retirement_income, first_gap)
    sustainable_value = (
        _money(sustainable.annual_income) if sustainable.feasible else "Not available"
    )
    pre_retirement_gaps = projection[
        (~projection.retired) & (projection.shortfall > .01)
    ]
    if not pre_retirement_gaps.empty:
        gap_text = f"Pre-retirement shortfall from age {int(pre_retirement_gaps.iloc[0].age)}"
    elif first_gap is not None:
        gap_text = f"First shortfall at age {first_gap}"
    else:
        last = projection.iloc[-1]
        if h.partner_age is None:
            gap_text = f"No shortfall through age {int(last.age)}"
        else:
            gap_text = (
                f"No shortfall through ages {int(last.age)} and "
                f"{int(last.partner_age)}"
            )
    summary = Table(
        [[
            Paragraph("<b>Estimated sustainable income</b><br/>" + sustainable_value, styles["Cell"]),
            Paragraph("<b>Retirement income goal</b><br/>" + _money(h.retirement_income), styles["Cell"]),
            Paragraph(
                f"<b>Plan status</b><br/><font color='{status_color.hexval()}'>"
                f"{escape(status_text)}</font>",
                styles["Cell"],
            ),
            Paragraph("<b>Funding outlook</b><br/>" + escape(gap_text), styles["Cell"]),
        ]],
        colWidths=[doc.width * .25] * 4,
    )
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), .6, GRID),
        ("INNERGRID", (0, 0), (-1, -1), .5, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (2, 0), (2, 0), status_color),
    ]))
    story.extend([summary, Paragraph("Household and plan", styles["Section"])])
    household_rows = [
        [Paragraph("<b>People and retirement timing</b>", styles["Cell"]),
         Paragraph(escape(_age_range(h)), styles["Cell"])],
        [Paragraph("<b>Current spending</b>", styles["Cell"]),
         Paragraph(_money(h.annual_spending) + " per year", styles["Cell"])],
        [Paragraph("<b>Property and loan</b>", styles["Cell"]),
         Paragraph(
             f"Property {_money(h.property_value)} · interest-only balance "
             f"{_money(h.investment_loan_balance)} at {h.investment_loan_rate:.2%}",
             styles["Cell"],
         )],
        [Paragraph("<b>Key assumptions</b>", styles["Cell"]),
         Paragraph(
             f"Inflation {assumptions.inflation:.2%} · super return "
             f"{assumptions.super_return:.2%} · shares/funds return "
             f"{assumptions.investment_return:.2%} · life expectancy "
             f"{assumptions.life_expectancy}",
             styles["Cell"],
         )],
    ]
    household_table = Table(household_rows, colWidths=[48 * mm, doc.width - 48 * mm])
    household_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), .4, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(household_table)

    if h.lifestyle_goals:
        story.append(Paragraph("Lifestyle goals included", styles["Section"]))
        goal_rows = [[
            Paragraph("<b>Goal</b>", styles["Cell"]),
            Paragraph("<b>Amount</b>", styles["Cell"]),
            Paragraph("<b>Frequency</b>", styles["Cell"]),
            Paragraph("<b>Age range</b>", styles["Cell"]),
        ]]
        for goal in h.lifestyle_goals:
            goal_rows.append([
                Paragraph(escape(goal.category), styles["Cell"]),
                Paragraph(_money(goal.amount), styles["Cell"]),
                Paragraph(escape(goal.frequency), styles["Cell"]),
                Paragraph(
                    f"{goal.start_age}" if goal.frequency == "One-off"
                    else f"{goal.start_age} to {goal.finish_age}",
                    styles["Cell"],
                ),
            ])
        goals_table = Table(goal_rows, colWidths=[55 * mm, 45 * mm, 50 * mm, 45 * mm], repeatRows=1)
        goals_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PALE),
            ("GRID", (0, 0), (-1, -1), .4, GRID),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(goals_table)

    story.extend([
        Paragraph("Year-by-year projection", styles["Section"]),
        Paragraph(
            "Balances are year-end estimates. Expenses include the retirement income "
            "goal, lifestyle goals, debt repayments and modeled investment-property "
            "interest. This table uses today's dollars.",
            styles["Small"],
        ),
        Spacer(1, 2 * mm),
    ])
    headers = [
        "Age", "Partner age", "Phase", "Super", "Shares / funds", "Cash",
        "Property", "Total debt", "Net worth", "Expenses", "Shortfall",
    ]
    projection_rows = [[Paragraph(f"<b>{header}</b>", styles["Cell"]) for header in headers]]
    for row in projection.to_dict("records"):
        phase = "Retired" if row["retired"] else "Working"
        projection_rows.append([
            str(int(row["age"])),
            "" if pd.isna(row["partner_age"]) else str(int(row["partner_age"])),
            phase,
            _money(row["super"]),
            _money(row["investments"]),
            _money(row["cash"]),
            _money(row["property"]),
            _money(row["mortgage"] + row["investment_loan"] + row["other_debts"]),
            _money(row["net_worth"]),
            _money(row["total_expenses"]),
            _money(row["shortfall"]),
        ])
    column_widths = [30, 42, 42, 75, 82, 65, 75, 75, 83, 75, 61]
    scale = doc.width / sum(column_widths)
    column_widths = [width * scale for width in column_widths]
    projection_table = LongTable(
        projection_rows, colWidths=column_widths, repeatRows=1, hAlign="LEFT",
    )
    projection_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), .35, GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 1), (-1, -1), 6.5),
        ("LEADING", (0, 1), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(projection_table)
    story.extend([
        Spacer(1, 4 * mm),
        Paragraph("<b>Model limitations and assumptions</b>", styles["Small"]),
    ])
    for limitation in projection.attrs.get("limitations", []):
        story.append(Paragraph(f"- {escape(limitation)}", styles["Small"]))
    warnings = projection.attrs.get("warnings", [])
    if warnings:
        story.append(Paragraph("<b>Projection adjustments</b>", styles["Small"]))
        for warning in warnings:
            story.append(Paragraph(
                f"- {escape(warning['message'])}", styles["Small"],
            ))
    story.extend([
        Spacer(1, 2 * mm),
        Paragraph(
            escape(DISCLAIMER) + " Estimates are based on simplified assumptions, "
            "not guarantees or a recommendation. Review all inputs and assumptions "
            "before sharing or relying on this report.",
            styles["Small"],
        ),
    ])
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
