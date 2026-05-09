from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for server use
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

from app.utils.logger import get_logger

logger = get_logger("chart_generator")

# Consistent style across all charts
plt.rcParams.update({
    "figure.dpi": 150,
    "figure.facecolor": "white",
    "axes.facecolor": "#f8f9fa",
    "axes.grid": True,
    "grid.color": "#dddddd",
    "grid.linestyle": "--",
    "grid.linewidth": 0.6,
    "font.family": "DejaVu Sans",
    "font.size": 10,
})

_PALETTE = [
    "#2563eb", "#16a34a", "#dc2626", "#d97706", "#7c3aed",
    "#0891b2", "#be185d", "#65a30d", "#9f1239", "#1d4ed8",
]


class ChartGenerator:
    """Generates matplotlib charts from a financial DataFrame."""

    # -----------------------------------------------------------------------
    # Revenue trend — line chart
    # -----------------------------------------------------------------------

    def revenue_trend(self, df: pd.DataFrame, output_path: str) -> str:
        """
        Monthly revenue trend line chart.

        Looks for a date column and a revenue column automatically.
        Returns the output path.
        """
        date_col = self._find_col(df, ["date", "period", "transaction_date"])
        rev_col = self._find_col(df, ["revenue", "income", "sales", "amount"])

        fig, ax = plt.subplots(figsize=(10, 5))

        if date_col and rev_col:
            df = df.copy()
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            monthly = (
                df.groupby(df[date_col].dt.to_period("M"))[rev_col]
                .sum()
                .reset_index()
            )
            monthly[date_col] = monthly[date_col].astype(str)
            ax.plot(
                monthly[date_col],
                monthly[rev_col],
                marker="o",
                linewidth=2.5,
                color=_PALETTE[0],
                markersize=6,
                label="Monthly Revenue",
            )
            ax.fill_between(
                monthly[date_col],
                monthly[rev_col],
                alpha=0.15,
                color=_PALETTE[0],
            )
            ax.set_xlabel("Month", fontsize=11)
            ax.set_ylabel("Revenue ($)", fontsize=11)
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
            plt.xticks(rotation=45, ha="right")
            ax.legend()
        else:
            ax.text(0.5, 0.5, "Insufficient data for revenue trend",
                    ha="center", va="center", transform=ax.transAxes, fontsize=13)

        ax.set_title("Monthly Revenue Trend", fontsize=14, fontweight="bold", pad=15)
        fig.tight_layout()
        fig.savefig(output_path, bbox_inches="tight")
        plt.close(fig)
        logger.info(f"revenue_trend saved to {output_path}")
        return output_path

    # -----------------------------------------------------------------------
    # Expense breakdown — pie chart
    # -----------------------------------------------------------------------

    def expense_breakdown(self, df: pd.DataFrame, output_path: str) -> str:
        """Pie chart of expenses broken down by category."""
        cat_col = self._find_col(df, ["category", "type", "department", "segment"])
        exp_col = self._find_col(df, ["expenses", "expense", "cost", "costs"])

        fig, ax = plt.subplots(figsize=(8, 7))

        if cat_col and exp_col:
            grouped = (
                df.groupby(cat_col)[exp_col]
                .sum()
                .nlargest(8)
                .clip(lower=0)
            )
            if grouped.sum() > 0:
                wedges, texts, autotexts = ax.pie(
                    grouped,
                    labels=grouped.index,
                    autopct="%1.1f%%",
                    colors=_PALETTE[: len(grouped)],
                    startangle=140,
                    pctdistance=0.82,
                    wedgeprops={"edgecolor": "white", "linewidth": 1.5},
                )
                for autotext in autotexts:
                    autotext.set_fontsize(9)
            else:
                ax.text(0.5, 0.5, "No expense data", ha="center", va="center",
                        transform=ax.transAxes, fontsize=13)
        else:
            ax.text(0.5, 0.5, "No category/expense columns found",
                    ha="center", va="center", transform=ax.transAxes, fontsize=13)

        ax.set_title("Expense Breakdown by Category", fontsize=14, fontweight="bold", pad=15)
        fig.tight_layout()
        fig.savefig(output_path, bbox_inches="tight")
        plt.close(fig)
        logger.info(f"expense_breakdown saved to {output_path}")
        return output_path

    # -----------------------------------------------------------------------
    # Profit margin bar chart
    # -----------------------------------------------------------------------

    def profit_margin_bar(self, df: pd.DataFrame, output_path: str) -> str:
        """Bar chart of monthly profit margins (%)."""
        date_col = self._find_col(df, ["date", "period", "transaction_date"])
        rev_col = self._find_col(df, ["revenue", "income", "sales", "amount"])
        exp_col = self._find_col(df, ["expenses", "expense", "cost", "costs"])

        fig, ax = plt.subplots(figsize=(10, 5))

        if date_col and rev_col and exp_col:
            df = df.copy()
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            monthly = (
                df.groupby(df[date_col].dt.to_period("M"))[[rev_col, exp_col]]
                .sum()
                .reset_index()
            )
            monthly["profit"] = monthly[rev_col] - monthly[exp_col]
            monthly["margin_pct"] = (
                (monthly["profit"] / monthly[rev_col].replace(0, float("nan"))) * 100
            ).fillna(0).round(1)
            monthly["period_str"] = monthly[date_col].astype(str)

            colors = [_PALETTE[1] if v >= 0 else _PALETTE[2] for v in monthly["margin_pct"]]
            bars = ax.bar(monthly["period_str"], monthly["margin_pct"], color=colors, width=0.6)
            ax.axhline(0, color="#374151", linewidth=1, linestyle="-")
            ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=8)
            ax.set_xlabel("Month", fontsize=11)
            ax.set_ylabel("Profit Margin (%)", fontsize=11)
            plt.xticks(rotation=45, ha="right")
        else:
            ax.text(0.5, 0.5, "Insufficient data for profit margin chart",
                    ha="center", va="center", transform=ax.transAxes, fontsize=13)

        ax.set_title("Monthly Profit Margin (%)", fontsize=14, fontweight="bold", pad=15)
        fig.tight_layout()
        fig.savefig(output_path, bbox_inches="tight")
        plt.close(fig)
        logger.info(f"profit_margin_bar saved to {output_path}")
        return output_path

    # -----------------------------------------------------------------------
    # Top N items horizontal bar
    # -----------------------------------------------------------------------

    def top_items_horizontal_bar(
        self,
        df: pd.DataFrame,
        column: str,
        n: int,
        output_path: str,
        value_col: Optional[str] = None,
    ) -> str:
        """
        Horizontal bar chart of the top *n* items in *column* by
        *value_col* (defaults to count if value_col is None).
        """
        fig, ax = plt.subplots(figsize=(9, max(4, n * 0.6)))

        if column in df.columns:
            if value_col and value_col in df.columns:
                top = df.groupby(column)[value_col].sum().nlargest(n)
                x_label = value_col.replace("_", " ").title()
            else:
                top = df[column].value_counts().head(n)
                x_label = "Count"

            top = top.sort_values(ascending=True)  # bottom to top
            colors = _PALETTE[: len(top)]
            bars = ax.barh(top.index.astype(str), top.values, color=colors, height=0.6)
            ax.bar_label(bars, fmt="{:,.0f}", padding=4, fontsize=9)
            ax.set_xlabel(x_label, fontsize=11)
            ax.set_ylabel(column.replace("_", " ").title(), fontsize=11)
        else:
            ax.text(0.5, 0.5, f"Column '{column}' not found",
                    ha="center", va="center", transform=ax.transAxes, fontsize=13)

        ax.set_title(f"Top {n} by {column.replace('_', ' ').title()}",
                     fontsize=14, fontweight="bold", pad=15)
        fig.tight_layout()
        fig.savefig(output_path, bbox_inches="tight")
        plt.close(fig)
        logger.info(f"top_items_horizontal_bar saved to {output_path}")
        return output_path

    # -----------------------------------------------------------------------
    # Generate all charts
    # -----------------------------------------------------------------------

    def generate_all(self, df: pd.DataFrame, output_dir: str) -> List[str]:
        """
        Generate all standard charts and return a list of file paths.
        Skips individual charts that fail without raising.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        paths: List[str] = []

        charts = [
            ("revenue_trend.png", lambda p: self.revenue_trend(df, p)),
            ("expense_breakdown.png", lambda p: self.expense_breakdown(df, p)),
            ("profit_margin.png", lambda p: self.profit_margin_bar(df, p)),
        ]

        # Add top-items chart if a category column exists
        cat_col = self._find_col(df, ["category", "type", "department", "segment"])
        rev_col = self._find_col(df, ["revenue", "income", "sales", "amount"])
        if cat_col:
            charts.append((
                "top_categories.png",
                lambda p: self.top_items_horizontal_bar(df, cat_col, 10, p, value_col=rev_col),
            ))

        for filename, fn in charts:
            chart_path = str(out / filename)
            try:
                fn(chart_path)
                paths.append(chart_path)
            except Exception as exc:
                logger.error(f"Chart '{filename}' failed: {exc}")

        return paths

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        for col in df.columns:
            for cand in candidates:
                if cand in col.lower():
                    return col
        return None
