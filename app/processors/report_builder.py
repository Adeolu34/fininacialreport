from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# ---------------------------------------------------------------------------
# ReportLab imports
# ---------------------------------------------------------------------------
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# openpyxl imports
# ---------------------------------------------------------------------------
import openpyxl
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import ColorScaleRule, CellIsRule
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    GradientFill,
    PatternFill,
    Side,
    numbers,
)
from openpyxl.utils import get_column_letter
from openpyxl.utils.dataframe import dataframe_to_rows

from app.utils.logger import get_logger

logger = get_logger("report_builder")

# Brand colours
BRAND_BLUE = colors.HexColor("#1e3a5f")
BRAND_LIGHT_BLUE = colors.HexColor("#2563eb")
BRAND_GREEN = colors.HexColor("#16a34a")
BRAND_RED = colors.HexColor("#dc2626")
BRAND_GREY = colors.HexColor("#f1f5f9")


class ReportBuilder:
    """Builds PDF and Excel financial reports."""

    COMPANY_NAME = "Financial Reporting System"
    COMPANY_TAGLINE = "Automated Financial Analytics"

    # ===================================================================== #
    #                           PDF BUILD                                    #
    # ===================================================================== #

    def build_pdf(
        self,
        data: pd.DataFrame,
        summary: Dict[str, Any],
        chart_paths: List[str],
        output_path: str,
    ) -> str:
        """
        Build a PDF with:
          - Company header
          - Summary KPI table
          - Embedded charts
          - Data sample table
          - Footer with page numbers
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=1.5 * cm,
            leftMargin=1.5 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            title="Financial Report",
            author=self.COMPANY_NAME,
        )

        styles = getSampleStyleSheet()
        story: List[Any] = []

        # ---- Header --------------------------------------------------------
        story += self._pdf_header(styles)

        # ---- Summary KPI table --------------------------------------------
        story.append(Spacer(1, 0.4 * cm))
        story += self._pdf_summary_section(summary, styles)

        # ---- Charts --------------------------------------------------------
        for chart_path in chart_paths:
            if os.path.exists(chart_path):
                story.append(PageBreak())
                story += self._pdf_chart_section(chart_path, styles)

        # ---- Data table ----------------------------------------------------
        if not data.empty:
            story.append(PageBreak())
            story += self._pdf_data_section(data, styles)

        # Build with page-number footer
        doc.build(
            story,
            onFirstPage=self._pdf_footer,
            onLaterPages=self._pdf_footer,
        )

        logger.info(f"PDF built at {output_path}")
        return output_path

    def _pdf_header(self, styles) -> List[Any]:
        title_style = ParagraphStyle(
            "ReportTitle",
            parent=styles["Title"],
            fontSize=22,
            textColor=BRAND_BLUE,
            spaceAfter=4,
            fontName="Helvetica-Bold",
        )
        sub_style = ParagraphStyle(
            "ReportSub",
            parent=styles["Normal"],
            fontSize=11,
            textColor=colors.grey,
            spaceAfter=2,
        )
        date_style = ParagraphStyle(
            "ReportDate",
            parent=styles["Normal"],
            fontSize=9,
            textColor=colors.grey,
            alignment=TA_RIGHT,
        )

        elements = [
            Paragraph(self.COMPANY_NAME, title_style),
            Paragraph(self.COMPANY_TAGLINE, sub_style),
            Paragraph(
                f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
                date_style,
            ),
            Spacer(1, 0.5 * cm),
            # Horizontal rule
            Table(
                [[""]],
                colWidths=[18 * cm],
                style=TableStyle([
                    ("LINEBELOW", (0, 0), (-1, -1), 2, BRAND_BLUE),
                ]),
            ),
        ]
        return elements

    def _pdf_summary_section(self, summary: Dict[str, Any], styles) -> List[Any]:
        section_style = ParagraphStyle(
            "SectionTitle",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=BRAND_BLUE,
            spaceBefore=10,
            spaceAfter=6,
            fontName="Helvetica-Bold",
        )

        kpi_rows = [
            ["KPI", "Value"],
            ["Total Revenue", f"${summary.get('total_revenue', 0):,.2f}"],
            ["Total Expenses", f"${summary.get('total_expenses', 0):,.2f}"],
            ["Net Profit", f"${summary.get('net_profit', 0):,.2f}"],
            ["Profit Margin", f"{summary.get('profit_margin_pct', 0):.1f}%"],
            ["Avg Transaction", f"${summary.get('avg_transaction', 0):,.2f}"],
            ["Total Rows", f"{summary.get('row_count', 0):,}"],
        ]

        kpi_style = TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 11),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, 1), (-1, -1), BRAND_GREY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_GREY]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("FONTSIZE", (0, 1), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ])

        # Highlight positive/negative net profit
        net = summary.get("net_profit", 0)
        profit_color = BRAND_GREEN if net >= 0 else BRAND_RED
        kpi_style.add("TEXTCOLOR", (1, 3), (1, 3), profit_color)
        kpi_style.add("FONTNAME", (1, 3), (1, 3), "Helvetica-Bold")

        top_cats = summary.get("top_categories", {})
        cat_rows = [["Category", "Revenue"]] + [
            [cat, f"${val:,.2f}"] for cat, val in list(top_cats.items())[:5]
        ]

        elements = [
            Paragraph("Executive Summary", section_style),
            Table(kpi_rows, colWidths=[9 * cm, 9 * cm], style=kpi_style),
        ]

        if len(cat_rows) > 1:
            elements += [
                Spacer(1, 0.4 * cm),
                Paragraph("Top Categories by Revenue", section_style),
                Table(
                    cat_rows,
                    colWidths=[9 * cm, 9 * cm],
                    style=TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), BRAND_LIGHT_BLUE),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_GREY]),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ]),
                ),
            ]

        return elements

    def _pdf_chart_section(self, chart_path: str, styles) -> List[Any]:
        section_style = ParagraphStyle(
            "ChartTitle",
            parent=styles["Heading3"],
            fontSize=12,
            textColor=BRAND_BLUE,
            spaceBefore=8,
            spaceAfter=6,
        )
        name = Path(chart_path).stem.replace("_", " ").title()
        img = Image(chart_path, width=16 * cm, height=9 * cm)
        img.hAlign = "CENTER"
        return [Paragraph(name, section_style), img]

    def _pdf_data_section(self, data: pd.DataFrame, styles) -> List[Any]:
        section_style = ParagraphStyle(
            "DataTitle",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=BRAND_BLUE,
            spaceAfter=6,
        )

        # Show up to 50 rows; exclude internal metadata columns
        display_df = data.loc[:, ~data.columns.str.startswith("_")].head(50)
        col_names = [str(c).replace("_", " ").title() for c in display_df.columns]

        rows = [col_names]
        for _, row in display_df.iterrows():
            rows.append([
                str(v)[:40] if not pd.isna(v) else ""
                for v in row
            ])

        col_count = len(col_names)
        col_width = max(2.5 * cm, (17 * cm) / col_count)

        table = Table(
            rows,
            colWidths=[col_width] * col_count,
            repeatRows=1,
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("FONTSIZE", (0, 1), (-1, -1), 7),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_GREY]),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]),
        )

        note_style = ParagraphStyle(
            "DataNote",
            parent=styles["Normal"],
            fontSize=8,
            textColor=colors.grey,
        )
        note = Paragraph(
            f"Showing {min(50, len(data))} of {len(data)} rows. "
            "Download the Excel file for full data.",
            note_style,
        )

        return [Paragraph("Data Sample", section_style), table, Spacer(1, 0.3 * cm), note]

    @staticmethod
    def _pdf_footer(canvas, doc) -> None:
        """Draw page number and generation date in the footer."""
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        width, _ = A4
        canvas.drawString(1.5 * cm, 1.2 * cm, "Financial Reporting System — Confidential")
        canvas.drawRightString(
            width - 1.5 * cm,
            1.2 * cm,
            f"Page {doc.page}",
        )
        canvas.restoreState()

    # ===================================================================== #
    #                          EXCEL BUILD                                   #
    # ===================================================================== #

    def build_excel(
        self,
        data: pd.DataFrame,
        summary: Dict[str, Any],
        output_path: str,
    ) -> str:
        """
        Build an Excel workbook with three sheets:
          1. Summary — formatted KPI cards
          2. Data — full data table with conditional formatting
          3. Charts — embedded bar chart
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        wb = openpyxl.Workbook()

        # Remove default sheet
        wb.remove(wb.active)

        self._excel_summary_sheet(wb, summary)
        self._excel_data_sheet(wb, data)
        self._excel_charts_sheet(wb, data, summary)

        wb.save(output_path)
        logger.info(f"Excel built at {output_path}")
        return output_path

    def _excel_summary_sheet(self, wb: openpyxl.Workbook, summary: Dict[str, Any]) -> None:
        ws = wb.create_sheet("Summary")
        ws.sheet_view.showGridLines = False

        # Column widths
        ws.column_dimensions["A"].width = 28
        ws.column_dimensions["B"].width = 22

        header_fill = PatternFill("solid", fgColor="1e3a5f")
        header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=12)
        label_font = Font(name="Calibri", bold=True, size=11, color="1e3a5f")
        value_font = Font(name="Calibri", size=11)
        green_font = Font(name="Calibri", bold=True, size=11, color="16a34a")
        red_font = Font(name="Calibri", bold=True, size=11, color="dc2626")
        thin_border = Border(
            bottom=Side(style="thin", color="CCCCCC"),
            top=Side(style="thin", color="CCCCCC"),
        )

        # Title row
        ws["A1"] = self.COMPANY_NAME
        ws["A1"].font = Font(name="Calibri", bold=True, size=16, color="1e3a5f")
        ws["A2"] = f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"
        ws["A2"].font = Font(name="Calibri", size=9, color="888888", italic=True)
        ws.row_dimensions[1].height = 28

        # Header row at row 4
        ws["A4"] = "KPI"
        ws["B4"] = "Value"
        for cell in [ws["A4"], ws["B4"]]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[4].height = 22

        kpis = [
            ("Total Revenue", summary.get("total_revenue", 0), "currency"),
            ("Total Expenses", summary.get("total_expenses", 0), "currency"),
            ("Net Profit", summary.get("net_profit", 0), "currency"),
            ("Profit Margin (%)", summary.get("profit_margin_pct", 0), "percent"),
            ("Average Transaction", summary.get("avg_transaction", 0), "currency"),
            ("Total Rows", summary.get("row_count", 0), "integer"),
        ]

        alt_fill = PatternFill("solid", fgColor="F1F5F9")

        for i, (kpi_name, kpi_val, fmt) in enumerate(kpis, start=5):
            ws[f"A{i}"] = kpi_name
            ws[f"A{i}"].font = label_font
            ws[f"A{i}"].border = thin_border

            if fmt == "currency":
                ws[f"B{i}"] = kpi_val
                ws[f"B{i}"].number_format = '#,##0.00'
            elif fmt == "percent":
                ws[f"B{i}"] = kpi_val / 100
                ws[f"B{i}"].number_format = '0.00%'
            else:
                ws[f"B{i}"] = kpi_val
                ws[f"B{i}"].number_format = '#,##0'

            # Colour net profit
            if kpi_name == "Net Profit":
                ws[f"B{i}"].font = green_font if kpi_val >= 0 else red_font
            else:
                ws[f"B{i}"].font = value_font

            ws[f"B{i}"].alignment = Alignment(horizontal="right")
            ws[f"B{i}"].border = thin_border

            if i % 2 == 0:
                ws[f"A{i}"].fill = alt_fill
                ws[f"B{i}"].fill = alt_fill

            ws.row_dimensions[i].height = 20

        # Top categories section
        top_cats = summary.get("top_categories", {})
        if top_cats:
            start_row = len(kpis) + 7
            ws[f"A{start_row}"] = "Top Categories by Revenue"
            ws[f"A{start_row}"].font = Font(name="Calibri", bold=True, size=13, color="1e3a5f")

            ws[f"A{start_row + 1}"] = "Category"
            ws[f"B{start_row + 1}"] = "Revenue"
            for cell in [ws[f"A{start_row + 1}"], ws[f"B{start_row + 1}"]]:
                cell.fill = PatternFill("solid", fgColor="2563eb")
                cell.font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
                cell.alignment = Alignment(horizontal="center")

            for j, (cat, val) in enumerate(list(top_cats.items())[:10], start=start_row + 2):
                ws[f"A{j}"] = cat
                ws[f"B{j}"] = val
                ws[f"B{j}"].number_format = '#,##0.00'
                if j % 2 == 0:
                    ws[f"A{j}"].fill = alt_fill
                    ws[f"B{j}"].fill = alt_fill

    def _excel_data_sheet(self, wb: openpyxl.Workbook, data: pd.DataFrame) -> None:
        ws = wb.create_sheet("Data")

        # Exclude internal columns
        display_df = data.loc[:, ~data.columns.str.startswith("_")].copy()

        # Write header
        header_fill = PatternFill("solid", fgColor="1e3a5f")
        header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)

        for col_idx, col_name in enumerate(display_df.columns, start=1):
            cell = ws.cell(row=1, column=col_idx, value=str(col_name).replace("_", " ").title())
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        ws.row_dimensions[1].height = 22

        # Write data rows
        for row_idx, (_, row) in enumerate(display_df.iterrows(), start=2):
            for col_idx, value in enumerate(row, start=1):
                if pd.isna(value):
                    value = None
                elif isinstance(value, pd.Timestamp):
                    value = value.to_pydatetime()
                ws.cell(row=row_idx, column=col_idx, value=value)

        # Auto-size columns
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

        # Conditional formatting: red fill for negative numbers
        num_col_indices = [
            i + 1
            for i, col in enumerate(display_df.columns)
            if pd.api.types.is_numeric_dtype(display_df[col])
        ]
        red_fill = PatternFill("solid", fgColor="FEE2E2")
        green_fill = PatternFill("solid", fgColor="DCFCE7")

        for col_idx in num_col_indices:
            col_letter = get_column_letter(col_idx)
            data_range = f"{col_letter}2:{col_letter}{len(display_df) + 1}"
            ws.conditional_formatting.add(
                data_range,
                CellIsRule(operator="lessThan", formula=["0"], fill=red_fill),
            )
            ws.conditional_formatting.add(
                data_range,
                CellIsRule(operator="greaterThan", formula=["0"], fill=green_fill),
            )

        # Freeze header row
        ws.freeze_panes = "A2"

        # Add table style
        if len(display_df) > 0:
            from openpyxl.worksheet.table import Table, TableStyleInfo
            tbl = Table(
                displayName="DataTable",
                ref=f"A1:{get_column_letter(len(display_df.columns))}{len(display_df) + 1}",
            )
            tbl.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium2",
                showFirstColumn=False,
                showLastColumn=False,
                showRowStripes=True,
                showColumnStripes=False,
            )
            ws.add_table(tbl)

    def _excel_charts_sheet(
        self, wb: openpyxl.Workbook, data: pd.DataFrame, summary: Dict[str, Any]
    ) -> None:
        ws = wb.create_sheet("Charts")
        ws["A1"] = "Charts & Visualisations"
        ws["A1"].font = Font(name="Calibri", bold=True, size=14, color="1e3a5f")
        ws["A2"] = "Charts are embedded in the PDF report. Summary data is shown below."
        ws["A2"].font = Font(name="Calibri", size=10, color="888888", italic=True)

        # Write monthly summary for charting
        date_col = next(
            (c for c in data.columns if any(k in c for k in ("date", "period"))), None
        )
        rev_col = next(
            (c for c in data.columns if any(k in c for k in ("revenue", "income", "sales", "amount"))), None
        )
        exp_col = next(
            (c for c in data.columns if any(k in c for k in ("expenses", "expense", "cost"))), None
        )

        if date_col and rev_col:
            df_copy = data.copy()
            df_copy[date_col] = pd.to_datetime(df_copy[date_col], errors="coerce")
            agg_dict = {rev_col: "sum"}
            if exp_col:
                agg_dict[exp_col] = "sum"
            monthly = (
                df_copy.groupby(df_copy[date_col].dt.to_period("M"))
                .agg(agg_dict)
                .reset_index()
            )
            monthly[date_col] = monthly[date_col].astype(str)

            start_row = 4
            ws.cell(row=start_row, column=1, value="Month").font = Font(bold=True)
            ws.cell(row=start_row, column=2, value="Revenue").font = Font(bold=True)
            if exp_col:
                ws.cell(row=start_row, column=3, value="Expenses").font = Font(bold=True)

            for r_idx, (_, row) in enumerate(monthly.iterrows(), start=start_row + 1):
                ws.cell(row=r_idx, column=1, value=row[date_col])
                ws.cell(row=r_idx, column=2, value=float(row[rev_col]))
                if exp_col:
                    ws.cell(row=r_idx, column=3, value=float(row[exp_col]))

            # Embedded bar chart
            if len(monthly) >= 2:
                chart = BarChart()
                chart.type = "col"
                chart.title = "Monthly Revenue vs Expenses"
                chart.style = 10
                chart.y_axis.title = "Amount ($)"
                chart.x_axis.title = "Month"

                n_rows = len(monthly)
                rev_ref = Reference(ws, min_col=2, min_row=start_row, max_row=start_row + n_rows)
                chart.add_data(rev_ref, titles_from_data=True)

                if exp_col:
                    exp_ref = Reference(ws, min_col=3, min_row=start_row, max_row=start_row + n_rows)
                    chart.add_data(exp_ref, titles_from_data=True)

                cats_ref = Reference(ws, min_col=1, min_row=start_row + 1, max_row=start_row + n_rows)
                chart.set_categories(cats_ref)
                chart.shape = 4
                ws.add_chart(chart, "E4")
