"""
Enterprise-grade PDF report generator using ReportLab.

Produces a polished, multi-section PDF that mirrors the structure of a
Deloitte / PwC style technical audit report.

Sections
--------
1. Cover Page
2. Table of Contents
3. Executive Summary
4. Quality Overview (cards)
5. Charts
6. Files Analysis Table
7. Issues Summary Table
8. Detailed Issues (one section per issue)
9. Top Files
10. Top Rules
11. Technical Debt Summary
"""

from __future__ import annotations

import io
import logging
import os
from xml.sax.saxutils import escape
from datetime import datetime
from typing import TYPE_CHECKING, Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    BaseDocTemplate,
    FrameBreak,
    HRFlowable,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import KeepTogether
from reportlab.lib.colors import HexColor, black, white

from models.issue import IssueType, Severity
from models.metrics import rating_letter, rating_color
from models.project import ReportData
from reports.base_report import BaseReport
from services.chart_service import ChartService
from services.recommendation_engine import RecommendationEngine

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _pdf_text(value: object) -> str:
    """Escape external text before passing it to ReportLab's XML parser."""
    return escape(str(value)).replace("\n", "<br/>")

# ---------------------------------------------------------------------------
# Brand colours (enterprise blue/slate palette)
# ---------------------------------------------------------------------------

PRIMARY      = HexColor("#1a237e")   # deep navy
SECONDARY    = HexColor("#283593")   # medium navy
ACCENT       = HexColor("#42a5f5")   # light blue
ACCENT2      = HexColor("#00bcd4")   # teal
SUCCESS      = HexColor("#4caf50")
WARNING      = HexColor("#ff9800")
DANGER       = HexColor("#f44336")
LIGHT_BG     = HexColor("#f0f4ff")
ALT_ROW      = HexColor("#f8f9fe")
TEXT_DARK    = HexColor("#212121")
TEXT_MEDIUM  = HexColor("#546e7a")
TEXT_LIGHT   = HexColor("#90a4ae")
RULE_LINE    = HexColor("#e0e0e0")
CARD_BORDER  = HexColor("#c5cae9")

W, H = A4   # 595 x 842 pts


# ---------------------------------------------------------------------------
# PDF Report class
# ---------------------------------------------------------------------------

class PDFReport(BaseReport):
    """
    Generates a complete enterprise PDF report from a :class:`ReportData`.
    """

    def __init__(self, output_dir: str = "output") -> None:
        super().__init__(output_dir)
        self._chart_svc  = ChartService()
        self._rec_engine = RecommendationEngine()
        self._styles     = self._build_styles()
        self._toc_entries: list[tuple[str, str]] = []  # (title, anchor)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def generate(self, data: ReportData) -> str:
        """Generate the PDF report and return the output file path."""
        path = self.output_path("Report.pdf")
        logger.info("Generating PDF report → %s", path)

        story: list[Any] = []

        # Pre-generate all charts once
        charts = self._render_charts(data)

        # Build story
        story += self._cover_page(data)
        story += self._toc_placeholder()
        story += self._executive_summary(data)
        story += self._quality_overview(data)
        story += self._charts_section(charts)
        story += self._files_analysis(data)
        story += self._issues_summary_table(data)
        story += self._detailed_issues(data)
        story += self._top_files_section(data)
        story += self._top_rules_section(data)
        story += self._technical_debt(data)

        # Build document with header/footer
        doc = self._build_doc(path, data)
        doc.build(
            story,
            onFirstPage=self._first_page_template(data),
            onLaterPages=self._later_page_template(data),
        )

        logger.info("PDF report generated – %d KB", os.path.getsize(path) // 1024)
        return path

    # ------------------------------------------------------------------
    # Document template
    # ------------------------------------------------------------------

    def _build_doc(self, path: str, data: ReportData) -> SimpleDocTemplate:
        return SimpleDocTemplate(
            path,
            pagesize=A4,
            leftMargin=2.0 * cm,
            rightMargin=2.0 * cm,
            topMargin=2.5 * cm,
            bottomMargin=2.5 * cm,
            title=data.report_title,
            author=data.company_name,
            subject=f"Code Quality Report – {data.project_key}",
        )

    # ------------------------------------------------------------------
    # Page templates (header / footer)
    # ------------------------------------------------------------------

    def _first_page_template(self, data: ReportData):
        """Called by ReportLab for the cover page – no header/footer."""
        def _fn(canvas, doc):
            pass
        return _fn

    def _later_page_template(self, data: ReportData):
        """Header + footer for all pages after the cover."""
        title = data.report_title

        def _fn(canvas, doc):
            canvas.saveState()
            # Header bar
            canvas.setFillColor(PRIMARY)
            canvas.rect(0, H - 1.2 * cm, W, 1.2 * cm, fill=True, stroke=False)
            canvas.setFillColor(white)
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawString(2.0 * cm, H - 0.8 * cm, title)
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(W - 2.0 * cm, H - 0.8 * cm, data.project_key)

            # Footer
            canvas.setFillColor(TEXT_LIGHT)
            canvas.rect(0, 0, W, 1.0 * cm, fill=True, stroke=False)
            canvas.setFillColor(TEXT_DARK)
            canvas.setFont("Helvetica", 7)
            canvas.drawString(2.0 * cm, 0.35 * cm,
                              f"{data.company_name} | Generated {self.format_date(data.generated_at)} | CONFIDENTIAL")
            canvas.setFont("Helvetica-Bold", 8)
            canvas.drawRightString(W - 2.0 * cm, 0.35 * cm, f"Page {doc.page}")
            canvas.restoreState()

        return _fn

    # ------------------------------------------------------------------
    # Cover page
    # ------------------------------------------------------------------

    def _cover_page(self, data: ReportData) -> list:
        s = self._styles
        elements: list[Any] = []

        # Full-bleed navy background
        elements.append(Spacer(1, 5 * cm))

        # Title block
        elements.append(
            Paragraph(data.report_title, s["CoverTitle"])
        )
        elements.append(Spacer(1, 0.5 * cm))
        elements.append(
            Paragraph(data.project_name, s["CoverSubtitle"])
        )
        elements.append(Spacer(1, 1.5 * cm))

        # Divider
        elements.append(HRFlowable(width="80%", thickness=2, color=ACCENT, spaceAfter=1.5 * cm))

        # Meta block
        meta_data = [
            ["Project Key",   data.project_key],
            ["Generated",     self.format_datetime(data.generated_at)],
            ["Quality Gate",  data.metrics.quality_gate_status],
            ["Total Issues",  str(len(data.issues))],
            ["Lines of Code", f"{data.metrics.ncloc:,}"],
        ]
        meta_table = Table(meta_data, colWidths=[5 * cm, 9 * cm])
        meta_table.setStyle(TableStyle([
            ("FONTNAME",    (0, 0), (-1, -1), "Helvetica"),
            ("FONTNAME",    (0, 0), (0, -1),  "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, -1), 11),
            ("TEXTCOLOR",   (0, 0), (0, -1),  ACCENT2),
            ("TEXTCOLOR",   (1, 0), (1, -1),  white),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [HexColor("#1e2a5e"), HexColor("#253070")]),
            ("TOPPADDING",  (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ]))
        elements.append(meta_table)

        elements.append(Spacer(1, 3 * cm))
        elements.append(
            Paragraph(
                "STRICTLY CONFIDENTIAL — For authorized personnel only",
                s["CoverDisclaimer"],
            )
        )
        elements.append(PageBreak())
        return elements

    # ------------------------------------------------------------------
    # Table of Contents (static text – dynamic TOC needs a two-pass build)
    # ------------------------------------------------------------------

    def _toc_placeholder(self) -> list:
        s = self._styles
        elements: list[Any] = [
            Paragraph("TABLE OF CONTENTS", s["SectionHeader"]),
            Spacer(1, 0.5 * cm),
        ]

        toc_items = [
            ("1.", "Executive Summary"),
            ("2.", "Quality Overview"),
            ("3.", "Charts & Visualisations"),
            ("4.", "Files Analysis"),
            ("5.", "Issues Summary"),
            ("6.", "Detailed Issues"),
            ("7.", "Top Files"),
            ("8.", "Top Rules"),
            ("9.", "Technical Debt"),
        ]

        for num, title in toc_items:
            row = Table([[Paragraph(f"{num} {title}", s["TOCEntry"]), ""]], colWidths=[13 * cm, 3 * cm])
            row.setStyle(TableStyle([
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE_LINE),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]))
            elements.append(row)

        elements.append(PageBreak())
        return elements

    # ------------------------------------------------------------------
    # Executive Summary
    # ------------------------------------------------------------------

    def _executive_summary(self, data: ReportData) -> list:
        s = self._styles
        m = data.metrics
        elements: list[Any] = [
            Paragraph("1. EXECUTIVE SUMMARY", s["SectionHeader"]),
            Spacer(1, 0.3 * cm),
        ]

        # Gate badge
        gate_color = SUCCESS if m.quality_gate_status == "OK" else DANGER
        gate_label = "PASSED ✓" if m.quality_gate_status == "OK" else "FAILED ✗"
        elements.append(
            Paragraph(
                f'Quality Gate: <font color="{gate_color.hexval()}">'
                f'<b>{gate_label}</b></font>',
                s["GateBadge"],
            )
        )
        elements.append(Spacer(1, 0.4 * cm))

        # Summary paragraph
        elements.append(Paragraph(
            f"This report presents a comprehensive code quality analysis of the <b>{data.project_name}</b> project "
            f"({data.project_key}), generated on <b>{self.format_date(data.generated_at)}</b>. "
            f"The analysis covers <b>{data.metrics.ncloc:,}</b> lines of code across "
            f"<b>{data.metrics.files}</b> files and identifies "
            f"<b>{len(data.issues)}</b> quality issues requiring attention.",
            s["BodyText"],
        ))
        elements.append(Spacer(1, 0.5 * cm))

        # Summary metrics table
        rows = [
            ["Metric", "Value", "Rating / Status"],
            ["Lines of Code (ncloc)", f"{m.ncloc:,}", "–"],
            ["Reliability Rating", f"{m.bugs} Bug(s)", m.reliability_rating_letter],
            ["Security Rating", f"{m.vulnerabilities} Vulnerability(ies)", m.security_rating_letter],
            ["Maintainability Rating", f"{m.code_smells} Code Smell(s)", m.sqale_rating_letter],
            ["Technical Debt", m.technical_debt_display, "–"],
            ["Coverage", f"{m.coverage:.1f}%", "–"],
            ["Duplicated Lines", f"{m.duplicated_lines_density:.1f}%", "–"],
            ["Open Issues", str(m.open_issues), "–"],
            ["Accepted Issues", str(m.accepted_issues), "–"],
            ["Resolved Issues", str(m.resolved_issues), "–"],
        ]

        col_w = [7 * cm, 5 * cm, 4 * cm]
        tbl = Table(rows, colWidths=col_w)
        style = [
            # Header
            ("BACKGROUND",    (0, 0), (-1, 0),  PRIMARY),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  white),
            ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0),  10),
            ("ALIGN",         (0, 0), (-1, 0),  "CENTER"),
            # Body
            ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE",      (0, 1), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, ALT_ROW]),
            ("GRID",          (0, 0), (-1, -1), 0.5, RULE_LINE),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]

        # Colour rating cells
        rating_col_idx = 2
        rating_to_bg = {"A": "#4caf50", "B": "#8bc34a", "C": "#ff9800", "D": "#f44336", "E": "#d32f2f"}
        for row_idx, row in enumerate(rows[1:], start=1):
            rating = row[2]
            if rating in rating_to_bg:
                style.append(("BACKGROUND", (rating_col_idx, row_idx), (rating_col_idx, row_idx),
                               HexColor(rating_to_bg[rating])))
                style.append(("TEXTCOLOR", (rating_col_idx, row_idx), (rating_col_idx, row_idx), white))
                style.append(("FONTNAME", (rating_col_idx, row_idx), (rating_col_idx, row_idx), "Helvetica-Bold"))
                style.append(("ALIGN", (rating_col_idx, row_idx), (rating_col_idx, row_idx), "CENTER"))

        tbl.setStyle(TableStyle(style))
        elements.append(tbl)
        elements.append(PageBreak())
        return elements

    # ------------------------------------------------------------------
    # Quality Overview (cards)
    # ------------------------------------------------------------------

    def _quality_overview(self, data: ReportData) -> list:
        s = self._styles
        m = data.metrics
        elements: list[Any] = [
            Paragraph("2. QUALITY OVERVIEW", s["SectionHeader"]),
            Spacer(1, 0.4 * cm),
        ]

        # Each card: [category, count_label, rating]
        cards = [
            ("🔴  RELIABILITY",      f"{m.bugs} Bug(s)",               m.reliability_rating_letter),
            ("🟡  MAINTAINABILITY",  f"{m.code_smells} Code Smell(s)",  m.sqale_rating_letter),
            ("🔒  SECURITY",         f"{m.vulnerabilities} Vuln(s)",    m.security_rating_letter),
            ("📊  COVERAGE",         f"{m.coverage:.1f}%",              "–"),
            ("📋  DUPLICATIONS",     f"{m.duplicated_lines_density:.1f}%", "–"),
            ("⚙️  DEBT",             m.technical_debt_display,           "–"),
        ]

        card_rows = []
        row_buf: list[Any] = []
        for i, (category, value, rating) in enumerate(cards):
            bg_color = HexColor(rating_color(rating)) if rating != "–" else SECONDARY
            card_content = [
                [Paragraph(category, s["CardTitle"])],
                [Paragraph(value, s["CardValue"])],
                [Paragraph(f"Rating: {rating}", s["CardRating"])],
            ]
            card_tbl = Table(card_content, colWidths=[5.5 * cm])
            card_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_BG),
                ("BACKGROUND",    (0, 0), (-1, 0),  PRIMARY),
                ("TEXTCOLOR",     (0, 0), (-1, 0),  white),
                ("TOPPADDING",    (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING",   (0, 0), (-1, -1), 10),
                ("BOX",           (0, 0), (-1, -1), 1, CARD_BORDER),
                ("LINEBELOW",     (0, 0), (-1, 0),  2, bg_color),
            ]))
            row_buf.append(card_tbl)

            if len(row_buf) == 3 or i == len(cards) - 1:
                # Pad to 3 columns
                while len(row_buf) < 3:
                    row_buf.append("")
                card_rows.append(row_buf)
                row_buf = []

        layout = Table(card_rows, colWidths=[5.8 * cm, 5.8 * cm, 5.8 * cm], rowHeights=None)
        layout.setStyle(TableStyle([
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",   (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
            ("LEFTPADDING",  (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(layout)
        elements.append(PageBreak())
        return elements

    # ------------------------------------------------------------------
    # Charts section
    # ------------------------------------------------------------------

    def _render_charts(self, data: ReportData) -> dict[str, bytes]:
        logger.info("Rendering charts …")
        cs = self._chart_svc
        return {
            "severity_pie":        cs.severity_pie(data),
            "type_pie":            cs.type_pie(data),
            "severity_bar":        cs.severity_bar(data),
            "issues_per_file":     cs.issues_per_file_bar(data),
            "top_rules":           cs.top_rules_bar(data),
            "security_dist":       cs.security_distribution_pie(data),
            "maintainability":     cs.maintainability_trend(data),
            "overview_bar":        cs.overview_summary_bar(data),
        }

    def _charts_section(self, charts: dict[str, bytes]) -> list:
        s = self._styles
        elements: list[Any] = [
            Paragraph("3. CHARTS & VISUALISATIONS", s["SectionHeader"]),
            Spacer(1, 0.3 * cm),
        ]

        def _img(key: str, w: float = 14 * cm) -> Image:
            buf = io.BytesIO(charts[key])
            img = Image(buf, width=w, height=w * 0.6)
            return img

        chart_pairs = [
            ("Severity Distribution", "severity_pie", "Issue Type Distribution", "type_pie"),
            ("Issue Count by Severity", "severity_bar", "Security Distribution", "security_dist"),
            ("Project Overview", "overview_bar", "Maintainability Trend", "maintainability"),
        ]

        for left_title, left_key, right_title, right_key in chart_pairs:
            row_data = [[
                [Paragraph(left_title,  s["ChartTitle"]), _img(left_key,  7.5 * cm)],
                [Paragraph(right_title, s["ChartTitle"]), _img(right_key, 7.5 * cm)],
            ]]
            row_tbl = Table(row_data, colWidths=[8 * cm, 8 * cm])
            row_tbl.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",  (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]))
            elements.append(row_tbl)
            elements.append(Spacer(1, 0.5 * cm))

        # Full-width charts
        for title, key in [("Top Files by Issue Count", "issues_per_file"),
                            ("Top Violated Rules",       "top_rules")]:
            elements.append(Paragraph(title, s["ChartTitle"]))
            buf = io.BytesIO(charts[key])
            img = Image(buf, width=16 * cm, height=9 * cm)
            elements.append(img)
            elements.append(Spacer(1, 0.5 * cm))

        elements.append(PageBreak())
        return elements

    # ------------------------------------------------------------------
    # Files Analysis Table
    # ------------------------------------------------------------------

    def _files_analysis(self, data: ReportData) -> list:
        s = self._styles
        elements: list[Any] = [
            Paragraph("4. FILES ANALYSIS", s["SectionHeader"]),
            Spacer(1, 0.3 * cm),
            Paragraph(
                f"Top {min(30, len(data.file_stats))} files ranked by total issue count.",
                s["SubHeading"],
            ),
            Spacer(1, 0.3 * cm),
        ]

        header = ["File", "Total", "Bugs", "Code Smells", "Vulns", "Effort"]
        rows = [header]
        for fa in sorted(data.file_stats, key=lambda x: x.total_issues, reverse=True)[:30]:
            effort_h = fa.effort_minutes // 60
            effort_m = fa.effort_minutes % 60
            effort_str = f"{effort_h}h {effort_m}m" if effort_h else f"{effort_m}m"
            rows.append([
                self.truncate(fa.file_name, 40),
                str(fa.total_issues),
                str(fa.bugs),
                str(fa.code_smells),
                str(fa.vulnerabilities),
                effort_str,
            ])

        col_w = [7 * cm, 1.5 * cm, 1.5 * cm, 2.5 * cm, 1.5 * cm, 2.5 * cm]
        tbl = Table(rows, colWidths=col_w, repeatRows=1)
        tbl.setStyle(self._standard_table_style())
        elements.append(tbl)
        elements.append(PageBreak())
        return elements

    # ------------------------------------------------------------------
    # Issues Summary Table
    # ------------------------------------------------------------------

    def _issues_summary_table(self, data: ReportData) -> list:
        s = self._styles
        elements: list[Any] = [
            Paragraph("5. ISSUES SUMMARY", s["SectionHeader"]),
            Spacer(1, 0.3 * cm),
            Paragraph(
                f"Compact overview of all {len(data.issues)} issues sorted by severity.",
                s["SubHeading"],
            ),
            Spacer(1, 0.3 * cm),
        ]

        header = ["#", "Sev", "Type", "Rule", "File", "Line", "Status", "Message"]
        rows = [header]

        for idx, issue in enumerate(data.issues_sorted_by_severity, start=1):
            rows.append([
                str(idx),
                issue.severity.value[:3],
                issue.issue_type.label[:8],
                issue.rule.split(":")[-1][:18],
                self.truncate(issue.file_name, 22),
                str(issue.display_line or "–"),
                issue.issue_status.value[:8],
                self.truncate(issue.message, 40),
            ])

        col_w = [0.8*cm, 1.3*cm, 1.8*cm, 3.2*cm, 3.5*cm, 0.9*cm, 1.5*cm, 5*cm]
        tbl = Table(rows, colWidths=col_w, repeatRows=1)
        base_style = self._standard_table_style()

        # Colour severity cells
        severity_colors_map = {
            "BLO": "#d32f2f", "CRI": "#f44336",
            "MAJ": "#ff9800", "MIN": "#ffc107", "INF": "#2196f3",
        }
        for row_idx, row in enumerate(rows[1:], start=1):
            sev = row[1]
            bg = severity_colors_map.get(sev)
            if bg:
                base_style.add("BACKGROUND", (1, row_idx), (1, row_idx), HexColor(bg))
                base_style.add("TEXTCOLOR",  (1, row_idx), (1, row_idx), white)
                base_style.add("FONTNAME",   (1, row_idx), (1, row_idx), "Helvetica-Bold")

        tbl.setStyle(base_style)
        elements.append(tbl)
        elements.append(PageBreak())
        return elements

    # ------------------------------------------------------------------
    # Detailed Issues
    # ------------------------------------------------------------------

    def _detailed_issues(self, data: ReportData) -> list:
        s = self._styles
        elements: list[Any] = [
            Paragraph("6. DETAILED ISSUES", s["SectionHeader"]),
            Spacer(1, 0.3 * cm),
        ]

        issues_sorted = data.issues_sorted_by_severity

        for idx, issue in enumerate(issues_sorted, start=1):
            rec = self._rec_engine.recommend(issue, data.sonar_url)

            # Get rule info
            rule = data.rules.get(issue.rule, {})
            rule_name = rule.get("name", issue.rule)
            rule_desc = self._strip_html(rule.get("mdDesc", rule.get("htmlDesc", "")))[:800]
            rule_remediation = self._strip_html(rule.get("mdNote", ""))[:400]

            sev_color = HexColor(issue.severity.color_hex)

            block: list[Any] = [
                # Issue header
                HRFlowable(width="100%", thickness=1.5, color=sev_color, spaceBefore=12, spaceAfter=8),
                Paragraph(f"Issue #{idx} — {_pdf_text(issue.rule)}", s["IssueHeader"]),

                # Meta table
                Table([
                    [Paragraph("<b>Severity</b>",     s["MetaKey"]),
                     Paragraph(_pdf_text(issue.severity.value), s["MetaVal"]),
                     Paragraph("<b>Type</b>",          s["MetaKey"]),
                     Paragraph(_pdf_text(issue.issue_type.label), s["MetaVal"])],
                    [Paragraph("<b>File</b>",          s["MetaKey"]),
                     Paragraph(_pdf_text(self.truncate(issue.file_path, 55)), s["MetaVal"]),
                     Paragraph("<b>Line</b>",          s["MetaKey"]),
                     Paragraph(str(issue.display_line or "–"),  s["MetaVal"])],
                    [Paragraph("<b>Status</b>",        s["MetaKey"]),
                     Paragraph(_pdf_text(issue.issue_status.value), s["MetaVal"]),
                     Paragraph("<b>Effort</b>",        s["MetaKey"]),
                     Paragraph(_pdf_text(issue.effort), s["MetaVal"])],
                ], colWidths=[2.8*cm, 5.8*cm, 2*cm, 5.8*cm]),

                Spacer(1, 0.2 * cm),

                # Problem
                Paragraph("📌 Problem", s["IssueSubHeader"]),
                Paragraph(_pdf_text(issue.message), s["IssueBody"]),
            ]

            if issue.code_snippet:
                block.append(Paragraph("💻 Code", s["IssueSubHeader"]))
                block.append(Paragraph(
                    f'<font name="Courier" size="7">{_pdf_text(issue.code_snippet)}</font>',
                    s["IssueBody"],
                ))

            # Why
            if rule_desc:
                block.append(Paragraph("❓ Why Is This an Issue?", s["IssueSubHeader"]))
                block.append(Paragraph(_pdf_text(rule_desc[:600]), s["IssueBody"]))

            # How to fix
            if rule_remediation:
                block.append(Paragraph("🔧 Remediation", s["IssueSubHeader"]))
                block.append(Paragraph(_pdf_text(rule_remediation[:400]), s["IssueBody"]))

            # Developer Recommendation
            block.append(Paragraph("💡 Developer Recommendation", s["IssueSubHeader"]))
            block.append(Paragraph(_pdf_text(rec.developer_recommendation), s["IssueBody"]))

            # Business Impact
            block.append(Paragraph("📈 Business Impact", s["IssueSubHeader"]))
            block.append(Paragraph(_pdf_text(rec.business_impact), s["IssueBody"]))

            # Priority / Difficulty / Time row
            pd_row = Table([[
                [Paragraph("<b>Priority</b>",   s["MetaKey"]), Paragraph(rec.priority.value,    s["MetaVal"])],
                [Paragraph("<b>Difficulty</b>", s["MetaKey"]), Paragraph(rec.difficulty.value,  s["MetaVal"])],
                [Paragraph("<b>Est. Time</b>",  s["MetaKey"]), Paragraph(rec.estimated_time,    s["MetaVal"])],
            ]], colWidths=[5.5*cm, 5.5*cm, 5.5*cm])
            pd_row.setStyle(TableStyle([
                ("VALIGN",      (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("BACKGROUND",  (0, 0), (-1, -1), LIGHT_BG),
                ("BOX",         (0, 0), (-1, -1), 0.5, RULE_LINE),
                ("TOPPADDING",  (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
            ]))
            block.append(Spacer(1, 0.2 * cm))
            block.append(pd_row)

            # SonarQube link
            if rec.sonar_url:
                block.append(Spacer(1, 0.15 * cm))
                block.append(Paragraph(
                    f'🔗 <a href="{rec.sonar_url}" color="#1565c0"><u>Open in SonarQube</u></a>',
                    s["Link"],
                ))

            elements.append(KeepTogether(block[:8]))  # keep header with first few fields
            elements.extend(block[8:])
            elements.append(Spacer(1, 0.3 * cm))

        elements.append(PageBreak())
        return elements

    # ------------------------------------------------------------------
    # Top Files
    # ------------------------------------------------------------------

    def _top_files_section(self, data: ReportData) -> list:
        s = self._styles
        elements: list[Any] = [
            Paragraph("7. TOP FILES", s["SectionHeader"]),
            Spacer(1, 0.3 * cm),
            Paragraph("Top 20 files with the highest number of quality issues.", s["SubHeading"]),
            Spacer(1, 0.3 * cm),
        ]

        header = ["Rank", "File", "Total", "Bugs", "Code Smells", "Vulns", "Blocker", "Critical"]
        rows = [header]
        for rank, fa in enumerate(data.top_files, start=1):
            rows.append([
                str(rank),
                self.truncate(fa.path, 50),
                str(fa.total_issues),
                str(fa.bugs),
                str(fa.code_smells),
                str(fa.vulnerabilities),
                str(fa.blocker),
                str(fa.critical),
            ])

        col_w = [1*cm, 7.5*cm, 1.5*cm, 1.2*cm, 2.5*cm, 1.2*cm, 1.8*cm, 1.8*cm]
        tbl = Table(rows, colWidths=col_w, repeatRows=1)
        tbl.setStyle(self._standard_table_style())
        elements.append(tbl)
        elements.append(PageBreak())
        return elements

    # ------------------------------------------------------------------
    # Top Rules
    # ------------------------------------------------------------------

    def _top_rules_section(self, data: ReportData) -> list:
        s = self._styles
        elements: list[Any] = [
            Paragraph("8. TOP RULES", s["SectionHeader"]),
            Spacer(1, 0.3 * cm),
            Paragraph("Top 20 most frequently violated SonarQube rules.", s["SubHeading"]),
            Spacer(1, 0.3 * cm),
        ]

        header = ["Rank", "Rule Key", "Violations", "Severity", "Type", "Sample Message"]
        rows = [header]
        for rank, ra in enumerate(data.top_rules, start=1):
            rows.append([
                str(rank),
                ra.rule_key,
                str(ra.count),
                ra.severity,
                ra.issue_type.replace("_", " ").title(),
                self.truncate(ra.message_sample, 45),
            ])

        col_w = [1*cm, 4.5*cm, 2*cm, 2*cm, 2.5*cm, 5.5*cm]
        tbl = Table(rows, colWidths=col_w, repeatRows=1)
        tbl.setStyle(self._standard_table_style())
        elements.append(tbl)
        elements.append(PageBreak())
        return elements

    # ------------------------------------------------------------------
    # Technical Debt
    # ------------------------------------------------------------------

    def _technical_debt(self, data: ReportData) -> list:
        s = self._styles
        m = data.metrics
        elements: list[Any] = [
            Paragraph("9. TECHNICAL DEBT", s["SectionHeader"]),
            Spacer(1, 0.3 * cm),
        ]

        avg_per_file = (m.sqale_index / max(m.files, 1))
        avg_h = int(avg_per_file // 60)
        avg_m = int(avg_per_file % 60)

        rows = [
            ["Metric", "Value"],
            ["Total Technical Debt", m.technical_debt_display],
            ["Debt Ratio", f"{m.sqale_debt_ratio:.2f}%"],
            ["Estimated Total Effort (issues)", data.total_effort_display],
            ["Average Debt per File", f"{avg_h}h {avg_m}m" if avg_h else f"{avg_m}m"],
            ["Files Analysed", str(m.files)],
            ["Functions", str(m.functions)],
            ["Cyclomatic Complexity", str(m.complexity)],
            ["Cognitive Complexity", str(m.cognitive_complexity)],
            ["Comment Density", f"{m.comment_lines_density:.1f}%"],
        ]

        col_w = [9 * cm, 7 * cm]
        tbl = Table(rows, colWidths=col_w, repeatRows=1)
        tbl.setStyle(self._standard_table_style())
        elements.append(tbl)

        elements.append(Spacer(1, 1 * cm))
        elements.append(Paragraph(
            "Technical debt represents the estimated time required to remediate all code quality issues. "
            "A lower debt ratio (< 5%) indicates a healthy, maintainable codebase. "
            "Addressing high-severity issues first maximises return on investment.",
            s["BodyText"],
        ))

        return elements

    # ------------------------------------------------------------------
    # Style helpers
    # ------------------------------------------------------------------

    def _build_styles(self) -> dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()
        st: dict[str, ParagraphStyle] = {}

        def _s(name: str, **kw) -> ParagraphStyle:
            return ParagraphStyle(name, **kw)

        st["CoverTitle"] = _s("CoverTitle",
            fontName="Helvetica-Bold", fontSize=28, textColor=PRIMARY,
            alignment=TA_CENTER, spaceAfter=12, leading=34)
        st["CoverSubtitle"] = _s("CoverSubtitle",
            fontName="Helvetica", fontSize=18, textColor=SECONDARY,
            alignment=TA_CENTER, spaceAfter=8)
        st["CoverDisclaimer"] = _s("CoverDisclaimer",
            fontName="Helvetica", fontSize=8, textColor=TEXT_LIGHT,
            alignment=TA_CENTER)
        st["SectionHeader"] = _s("SectionHeader",
            fontName="Helvetica-Bold", fontSize=14, textColor=white,
            backColor=PRIMARY, borderPad=8, leading=20,
            spaceAfter=10, spaceBefore=8,
            leftIndent=-10, rightIndent=-10)
        st["SubHeading"] = _s("SubHeading",
            fontName="Helvetica-BoldOblique", fontSize=10, textColor=SECONDARY,
            spaceAfter=4)
        st["BodyText"] = _s("BodyText",
            fontName="Helvetica", fontSize=9, textColor=TEXT_DARK,
            leading=14, spaceAfter=6)
        st["TOCEntry"] = _s("TOCEntry",
            fontName="Helvetica", fontSize=10, textColor=TEXT_DARK,
            spaceAfter=2)
        st["GateBadge"] = _s("GateBadge",
            fontName="Helvetica-Bold", fontSize=13, spaceAfter=6)
        st["CardTitle"] = _s("CardTitle",
            fontName="Helvetica-Bold", fontSize=9, textColor=white, leading=12)
        st["CardValue"] = _s("CardValue",
            fontName="Helvetica-Bold", fontSize=16, textColor=PRIMARY, leading=20)
        st["CardRating"] = _s("CardRating",
            fontName="Helvetica", fontSize=9, textColor=TEXT_MEDIUM)
        st["ChartTitle"] = _s("ChartTitle",
            fontName="Helvetica-Bold", fontSize=10, textColor=SECONDARY,
            alignment=TA_CENTER, spaceAfter=4)
        st["IssueHeader"] = _s("IssueHeader",
            fontName="Helvetica-Bold", fontSize=11, textColor=PRIMARY, spaceAfter=6)
        st["IssueSubHeader"] = _s("IssueSubHeader",
            fontName="Helvetica-Bold", fontSize=9, textColor=SECONDARY,
            spaceBefore=6, spaceAfter=2)
        st["IssueBody"] = _s("IssueBody",
            fontName="Helvetica", fontSize=8, textColor=TEXT_DARK, leading=12, spaceAfter=4)
        st["MetaKey"] = _s("MetaKey",
            fontName="Helvetica-Bold", fontSize=8, textColor=TEXT_MEDIUM)
        st["MetaVal"] = _s("MetaVal",
            fontName="Helvetica", fontSize=8, textColor=TEXT_DARK)
        st["Link"] = _s("Link",
            fontName="Helvetica", fontSize=8, textColor=HexColor("#1565c0"))
        return st

    @staticmethod
    def _standard_table_style() -> TableStyle:
        return TableStyle([
            # Header row
            ("BACKGROUND",    (0, 0), (-1, 0),  PRIMARY),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  white),
            ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0),  9),
            ("ALIGN",         (0, 0), (-1, 0),  "CENTER"),
            # Body
            ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE",      (0, 1), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, ALT_ROW]),
            ("GRID",          (0, 0), (-1, -1), 0.3, RULE_LINE),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ])

    @staticmethod
    def _strip_html(html: str) -> str:
        """Remove HTML tags for plain-text rendering in ReportLab paragraphs."""
        import re
        text = re.sub(r"<[^>]+>", " ", html or "")
        text = re.sub(r"\s+", " ", text).strip()
        return text
