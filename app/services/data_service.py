from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pandas as pd

from app.utils.logger import get_logger

logger = get_logger("data_service")


@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    row_count: int = 0
    null_counts: dict = field(default_factory=dict)


class DataService:
    """High-level data loading, cleaning, combining, and summarising."""

    # Columns that are tried as the revenue column (case-insensitive)
    _REVENUE_CANDIDATES = ["revenue", "income", "sales", "amount", "total", "gross"]
    _EXPENSE_CANDIDATES = ["expenses", "expense", "cost", "costs", "expenditure", "spend"]
    _DATE_CANDIDATES = ["date", "transaction_date", "period", "report_date", "created_at"]
    _CATEGORY_CANDIDATES = ["category", "type", "department", "segment", "group"]

    # -----------------------------------------------------------------------
    # Loading
    # -----------------------------------------------------------------------

    def load_excel_files(self, file_paths: List[str]) -> List[pd.DataFrame]:
        """Read multiple Excel or CSV files and return a list of DataFrames."""
        dfs: List[pd.DataFrame] = []
        for path_str in file_paths:
            path = Path(path_str)
            if not path.exists():
                logger.warning(f"File not found, skipping: {path}")
                continue
            try:
                suffix = path.suffix.lower()
                if suffix in (".xls", ".xlsx", ".xlsm", ".xlsb"):
                    df = pd.read_excel(path, engine="openpyxl")
                elif suffix == ".csv":
                    df = pd.read_csv(path)
                else:
                    logger.warning(f"Unsupported file type: {path}")
                    continue
                df["_source_file"] = path.name
                dfs.append(df)
                logger.info(f"Loaded {len(df)} rows from {path.name}")
            except Exception as exc:
                logger.error(f"Failed to load {path}: {exc}")
        return dfs

    # -----------------------------------------------------------------------
    # Cleaning
    # -----------------------------------------------------------------------

    def clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply standard cleaning:
        - Normalize column names to snake_case
        - Strip whitespace from string columns
        - Parse obvious date columns
        - Drop fully-empty rows
        - Fill NaN with sensible defaults
        - Remove duplicate rows
        """
        # Normalize column names
        df = df.copy()
        df.columns = [self._normalize_col_name(c) for c in df.columns]

        # Strip string columns
        str_cols = df.select_dtypes(include="object").columns
        for col in str_cols:
            df[col] = df[col].astype(str).str.strip()
            df[col] = df[col].replace({"nan": pd.NA, "None": pd.NA, "": pd.NA})

        # Parse date columns
        for col in df.columns:
            if any(kw in col for kw in ("date", "period", "time", "created", "updated")):
                try:
                    df[col] = pd.to_datetime(df[col], errors="coerce", infer_datetime_format=True)
                except Exception:
                    pass

        # Drop fully-empty rows
        df.dropna(how="all", inplace=True)

        # Fill numeric NaN with 0
        num_cols = df.select_dtypes(include="number").columns
        df[num_cols] = df[num_cols].fillna(0)

        # Fill remaining string NaN with empty string
        str_cols = df.select_dtypes(include="object").columns
        df[str_cols] = df[str_cols].fillna("")

        # Remove duplicates
        df.drop_duplicates(inplace=True)
        df.reset_index(drop=True, inplace=True)

        return df

    # -----------------------------------------------------------------------
    # Combining
    # -----------------------------------------------------------------------

    def combine_dataframes(self, dfs: List[pd.DataFrame]) -> pd.DataFrame:
        """
        Concatenate multiple DataFrames with source tracking.
        Adds a ``_source_index`` column indicating which input DataFrame the
        row originated from.
        """
        if not dfs:
            return pd.DataFrame()

        tagged: List[pd.DataFrame] = []
        for idx, df in enumerate(dfs):
            df = df.copy()
            if "_source_index" not in df.columns:
                df["_source_index"] = idx
            tagged.append(df)

        combined = pd.concat(tagged, ignore_index=True, sort=False)
        combined.reset_index(drop=True, inplace=True)
        logger.info(f"Combined {len(dfs)} DataFrames into {len(combined)} total rows")
        return combined

    # -----------------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------------

    def validate_data(self, df: pd.DataFrame) -> ValidationResult:
        """
        Validate the combined DataFrame:
        - Check for revenue/expense columns
        - Check for date column
        - Report null counts in critical fields
        - Warn on very low row counts
        """
        errors: List[str] = []
        warnings: List[str] = []
        null_counts: dict = {}

        if df.empty:
            errors.append("DataFrame is empty")
            return ValidationResult(is_valid=False, errors=errors, row_count=0)

        # Check for revenue column
        rev_col = self._find_column(df, self._REVENUE_CANDIDATES)
        if rev_col is None:
            warnings.append("No revenue/income column detected")

        # Check for expense column
        exp_col = self._find_column(df, self._EXPENSE_CANDIDATES)
        if exp_col is None:
            warnings.append("No expenses column detected")

        # Check for date column
        date_col = self._find_column(df, self._DATE_CANDIDATES)
        if date_col is None:
            warnings.append("No date column detected; time-series charts will be skipped")

        # Null counts for numeric columns
        num_cols = df.select_dtypes(include="number").columns.tolist()
        for col in num_cols:
            n_null = int(df[col].isna().sum())
            if n_null > 0:
                null_counts[col] = n_null
                warnings.append(f"Column '{col}' has {n_null} null values")

        # Row-count sanity
        if len(df) < 5:
            warnings.append(f"Very low row count: {len(df)}")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            row_count=len(df),
            null_counts=null_counts,
        )

    # -----------------------------------------------------------------------
    # Summary computation
    # -----------------------------------------------------------------------

    def compute_summary(self, df: pd.DataFrame) -> dict:
        """
        Compute high-level KPIs from the DataFrame.

        Returns
        -------
        dict with keys:
            total_revenue, total_expenses, net_profit, avg_transaction,
            top_categories, row_count, revenue_col, expense_col
        """
        summary: dict = {"row_count": len(df)}

        rev_col = self._find_column(df, self._REVENUE_CANDIDATES)
        exp_col = self._find_column(df, self._EXPENSE_CANDIDATES)
        cat_col = self._find_column(df, self._CATEGORY_CANDIDATES)

        total_revenue = float(df[rev_col].sum()) if rev_col else 0.0
        total_expenses = float(df[exp_col].sum()) if exp_col else 0.0
        net_profit = total_revenue - total_expenses
        avg_transaction = float(df[rev_col].mean()) if rev_col else 0.0

        top_categories: dict = {}
        if cat_col and rev_col:
            top_categories = (
                df.groupby(cat_col)[rev_col]
                .sum()
                .nlargest(5)
                .round(2)
                .to_dict()
            )

        summary.update({
            "total_revenue": round(total_revenue, 2),
            "total_expenses": round(total_expenses, 2),
            "net_profit": round(net_profit, 2),
            "profit_margin_pct": round((net_profit / total_revenue * 100) if total_revenue else 0, 2),
            "avg_transaction": round(avg_transaction, 2),
            "top_categories": top_categories,
            "revenue_col": rev_col,
            "expense_col": exp_col,
            "category_col": cat_col,
        })

        return summary

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _normalize_col_name(name: str) -> str:
        """Convert a column name to lowercase snake_case."""
        name = str(name).strip()
        name = re.sub(r"[\s\-]+", "_", name)
        name = re.sub(r"[^\w]", "", name)
        return name.lower()

    @staticmethod
    def _find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        """Return the first column in *df* whose name matches any candidate keyword."""
        for col in df.columns:
            for cand in candidates:
                if cand in col.lower():
                    return col
        return None
