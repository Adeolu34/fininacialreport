from __future__ import annotations

import re
from typing import Dict, List, Literal

import numpy as np
import pandas as pd

from app.utils.logger import get_logger

logger = get_logger("data_cleaner")

FillStrategy = Literal["mean", "median", "ffill", "bfill", "zero", "mode"]


class DataCleaner:
    """
    Fine-grained DataFrame cleaning utilities.

    All methods return a *new* DataFrame; the original is never mutated.
    """

    # -----------------------------------------------------------------------
    # Duplicate removal
    # -----------------------------------------------------------------------

    def remove_duplicates(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Remove exact duplicate rows and optionally near-duplicate rows based
        on business-key columns (if present).
        """
        before = len(df)
        df = df.drop_duplicates().reset_index(drop=True)
        removed = before - len(df)
        if removed:
            logger.info(f"remove_duplicates: removed {removed} exact duplicate row(s)")
        return df

    # -----------------------------------------------------------------------
    # Currency normalisation
    # -----------------------------------------------------------------------

    def normalize_currency(self, df: pd.DataFrame, column: str) -> pd.DataFrame:
        """
        Strip currency symbols, thousand separators, and parenthetical negatives,
        then cast the column to float64.

        Handles patterns like:
            $1,234.56  →  1234.56
            (500.00)   →  -500.00   (accounting notation)
            £1.2M      →  1200000.0
            €-3.5K     →  -3500.0
        """
        if column not in df.columns:
            logger.warning(f"normalize_currency: column '{column}' not found")
            return df

        df = df.copy()
        raw = df[column].astype(str)

        # Detect accounting parentheses for negatives
        is_negative = raw.str.strip().str.match(r"^\(.*\)$")

        # Strip currency symbols and whitespace
        raw = raw.str.replace(r"[£$€¥₦,\s]", "", regex=True)
        raw = raw.str.replace(r"[()]", "", regex=True)

        # Handle K/M/B multipliers
        multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
        for suffix, factor in multipliers.items():
            mask = raw.str.upper().str.endswith(suffix)
            raw.loc[mask] = (
                pd.to_numeric(raw.loc[mask].str[:-1], errors="coerce") * factor
            ).astype(str)

        numeric = pd.to_numeric(raw, errors="coerce")
        numeric = numeric.where(~is_negative, -numeric.abs())
        df[column] = numeric

        null_count = int(df[column].isna().sum())
        if null_count:
            logger.warning(f"normalize_currency: {null_count} value(s) could not be parsed in '{column}'")

        return df

    # -----------------------------------------------------------------------
    # Date parsing
    # -----------------------------------------------------------------------

    def parse_dates(self, df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        """
        Parse date columns that may contain mixed or non-standard formats.

        Tries common explicit formats before falling back to pandas inference.
        """
        _FORMATS = [
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%d-%m-%Y",
            "%m-%d-%Y",
            "%d %b %Y",
            "%d %B %Y",
            "%b %d, %Y",
            "%B %d, %Y",
            "%Y%m%d",
            "%d.%m.%Y",
        ]

        df = df.copy()
        for col in columns:
            if col not in df.columns:
                logger.warning(f"parse_dates: column '{col}' not found, skipping")
                continue

            series = df[col].astype(str).str.strip()
            parsed: pd.Series | None = None

            for fmt in _FORMATS:
                try:
                    attempt = pd.to_datetime(series, format=fmt, errors="coerce")
                    success_rate = attempt.notna().mean()
                    if success_rate > 0.5:  # majority parsed successfully
                        parsed = attempt
                        logger.debug(f"parse_dates: '{col}' matched format '{fmt}' ({success_rate:.0%})")
                        break
                except Exception:
                    continue

            if parsed is None:
                parsed = pd.to_datetime(series, errors="coerce", infer_datetime_format=True)
                logger.debug(f"parse_dates: '{col}' used inferred format")

            null_count = int(parsed.isna().sum())
            if null_count:
                logger.warning(f"parse_dates: {null_count} date(s) could not be parsed in '{col}'")

            df[col] = parsed

        return df

    # -----------------------------------------------------------------------
    # Fill missing values
    # -----------------------------------------------------------------------

    def fill_missing_values(
        self,
        df: pd.DataFrame,
        strategy: FillStrategy | Dict[str, FillStrategy] = "mean",
    ) -> pd.DataFrame:
        """
        Fill NaN values according to *strategy*.

        Parameters
        ----------
        df : pd.DataFrame
        strategy : str or dict
            - If str: apply the same strategy to all suitable columns.
            - If dict: map column_name → strategy for per-column control.
              Columns not in the dict get ``"mean"`` for numeric, ``"ffill"`` for object.

        Supported strategies: "mean", "median", "ffill", "bfill", "zero", "mode"
        """
        df = df.copy()
        num_cols = df.select_dtypes(include="number").columns.tolist()
        obj_cols = df.select_dtypes(include="object").columns.tolist()
        date_cols = df.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns.tolist()

        def _fill_column(col: str, strat: FillStrategy) -> None:
            if strat == "mean" and col in num_cols:
                df[col].fillna(df[col].mean(), inplace=True)
            elif strat == "median" and col in num_cols:
                df[col].fillna(df[col].median(), inplace=True)
            elif strat == "zero" and col in num_cols:
                df[col].fillna(0, inplace=True)
            elif strat == "mode":
                mode_val = df[col].mode()
                if not mode_val.empty:
                    df[col].fillna(mode_val.iloc[0], inplace=True)
            elif strat == "ffill":
                df[col].ffill(inplace=True)
            elif strat == "bfill":
                df[col].bfill(inplace=True)

        if isinstance(strategy, dict):
            for col, strat in strategy.items():
                if col in df.columns:
                    _fill_column(col, strat)
            # Apply defaults for remaining columns
            for col in num_cols:
                if col not in strategy:
                    _fill_column(col, "mean")
            for col in obj_cols:
                if col not in strategy:
                    _fill_column(col, "ffill")
        else:
            for col in num_cols:
                _fill_column(col, strategy if strategy not in ("ffill", "bfill") else "mean")
            for col in obj_cols:
                _fill_column(col, "ffill")
            for col in date_cols:
                _fill_column(col, "ffill")

        return df

    # -----------------------------------------------------------------------
    # Anomaly detection
    # -----------------------------------------------------------------------

    def detect_anomalies(self, df: pd.DataFrame, column: str) -> pd.DataFrame:
        """
        Flag outliers in *column* using the IQR method.

        Adds a boolean column ``{column}_is_outlier`` and a float column
        ``{column}_zscore`` to the returned DataFrame.

        A value is flagged as an outlier if it falls outside
        [Q1 - 1.5×IQR, Q3 + 1.5×IQR].
        """
        if column not in df.columns:
            logger.warning(f"detect_anomalies: column '{column}' not found")
            return df

        df = df.copy()
        series = pd.to_numeric(df[column], errors="coerce").dropna()

        if series.empty:
            logger.warning(f"detect_anomalies: no numeric data in '{column}'")
            df[f"{column}_is_outlier"] = False
            return df

        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr

        numeric_col = pd.to_numeric(df[column], errors="coerce")
        df[f"{column}_is_outlier"] = (numeric_col < lower_bound) | (numeric_col > upper_bound)

        mean = series.mean()
        std = series.std()
        if std > 0:
            df[f"{column}_zscore"] = ((numeric_col - mean) / std).round(3)
        else:
            df[f"{column}_zscore"] = 0.0

        outlier_count = int(df[f"{column}_is_outlier"].sum())
        logger.info(
            f"detect_anomalies: '{column}' — {outlier_count} outlier(s) "
            f"(bounds [{lower_bound:.2f}, {upper_bound:.2f}])"
        )
        return df
