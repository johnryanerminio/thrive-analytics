"""
DataStore — In-memory query engine backed by pandas.

Loaded once at startup, queried on every request.
Designed so swapping to Parquet/SQLite later only changes load() and query methods.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

import pandas as pd

from app.config import INBOX_FOLDER
from app.data.loader import (
    load_all_csvs,
    discover_bt_csvs,
    discover_customer_csvs,
    load_bt_performance,
    load_customer_attributes,
)
from app.data.schemas import PeriodFilter


class DataStore:
    """In-memory sales data with period-filtered accessors."""

    def __init__(self) -> None:
        self.df: pd.DataFrame = pd.DataFrame()
        self.bt_df: Optional[pd.DataFrame] = None
        self.cust_attr_df: Optional[pd.DataFrame] = None
        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, inbox: Path = INBOX_FOLDER) -> "DataStore":
        """Load all CSVs from inbox, deduplicate, classify."""
        print("Loading sales data...")
        self.df = load_all_csvs(inbox)

        if self.df.empty:
            print("  No sales CSVs found — starting with empty dataset")
            self._regular = self.df
        else:
            # Pre-filter REGULAR transactions — avoids re-filtering 4.8M rows on every request
            self._regular = self.df[self.df["transaction_type"] == "REGULAR"]
            print(f"  Pre-cached {len(self._regular):,} regular transactions")

        # BT performance — use most recent file
        bt_files = discover_bt_csvs(inbox)
        if bt_files:
            self.bt_df = load_bt_performance(bt_files[0])
            print(f"  BT performance: {bt_files[0].name} ({len(self.bt_df):,} rows)")

        # Customer attributes — use most recent file
        cust_files = discover_customer_csvs(inbox)
        if cust_files:
            self.cust_attr_df = load_customer_attributes(cust_files[0])
            print(f"  Customer attributes: {cust_files[0].name} ({len(self.cust_attr_df):,} rows)")

        self._loaded = True
        return self

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _apply_period(self, df: pd.DataFrame, period: PeriodFilter) -> pd.DataFrame:
        """Filter a DataFrame by period date range + optional store.

        Uses fast integer year/month columns for common period types
        instead of slow date comparisons on millions of rows.
        """
        from app.data.schemas import PeriodType

        if period.period_type == PeriodType.ALL:
            pass  # no date filter
        elif period.period_type == PeriodType.MONTH and period.year and period.month:
            df = df[(df["year"] == period.year) & (df["month"] == period.month)]
        elif period.period_type == PeriodType.QUARTER and period.year and period.quarter:
            m_start = (period.quarter - 1) * 3 + 1
            months = [m_start, m_start + 1, m_start + 2]
            df = df[(df["year"] == period.year) & (df["month"].isin(months))]
        elif period.period_type == PeriodType.YEAR and period.year:
            df = df[df["year"] == period.year]
        else:
            # Custom or fallback — use date comparison
            start, end = period.resolve()
            if start is not None and end is not None:
                df = df[(df["sale_date"] >= start) & (df["sale_date"] <= end)]
            elif start is not None:
                df = df[df["sale_date"] >= start]
            elif end is not None:
                df = df[df["sale_date"] <= end]

        if period.store:
            df = df[df["store_clean"] == period.store]
        return df

    def get_sales(self, period: PeriodFilter | None = None) -> pd.DataFrame:
        """All sales (including non-regular) for a period."""
        df = self.df
        if period:
            df = self._apply_period(df, period)
        return df.copy()

    def get_regular(self, period: PeriodFilter | None = None) -> pd.DataFrame:
        """Regular sales only (excludes rewards, markouts, testers, comps).

        Returns a filtered view (not a copy) for performance.
        Callers that need to mutate should call .copy() themselves.
        """
        df = self._regular
        if period:
            df = self._apply_period(df, period)
        return df

    def get_brand(self, brand: str, period: PeriodFilter | None = None) -> pd.DataFrame:
        """Regular sales for a specific brand."""
        df = self.get_regular(period)
        return df[df["brand_clean"].str.upper() == brand.upper()]

    # ------------------------------------------------------------------
    # Metadata queries
    # ------------------------------------------------------------------

    def stores(self) -> list[str]:
        """Unique store names (cleaned)."""
        if self.df.empty:
            return []
        return sorted(self.df["store_clean"].dropna().unique().tolist())

    def brands(self) -> list[str]:
        """Unique brand names sorted by revenue desc."""
        if self.df.empty:
            return []
        regular = self.df[self.df["transaction_type"] == "REGULAR"]
        rev = regular.groupby("brand_clean")["actual_revenue"].sum().sort_values(ascending=False)
        return rev.index.tolist()

    def categories(self) -> list[str]:
        """Unique category names sorted alphabetically."""
        if self.df.empty:
            return []
        return sorted(self.df["category_clean"].dropna().unique().tolist())

    def date_range(self, period: PeriodFilter | None = None) -> str:
        """Human-readable date range string.

        Uses pre-cached regular data for faster filtering.
        """
        df = self.get_regular(period)
        if df.empty:
            return "N/A"
        dates = df["sale_date"].dropna()
        if dates.empty:
            return "N/A"
        return f"{dates.min()} to {dates.max()}"

    def periods_available(self) -> list[dict]:
        """Return list of {year, month, label} dicts for months with data."""
        if self.df.empty:
            return []
        ym = self.df[["year", "month"]].drop_duplicates().sort_values(["year", "month"])
        result = []
        for _, row in ym.iterrows():
            y, m = int(row["year"]), int(row["month"])
            label = f"{dt.date(y, m, 1):%B %Y}"
            result.append({"year": y, "month": m, "label": label})
        return result

    def row_count(self) -> int:
        return len(self.df)

    def regular_count(self) -> int:
        if self.df.empty:
            return 0
        return (self.df["transaction_type"] == "REGULAR").sum()

    # ------------------------------------------------------------------
    # Category & brand lookups (for brand reports)
    # ------------------------------------------------------------------

    def category_margin_lookup(self, period: PeriodFilter | None = None) -> dict[str, float]:
        """Average margin by category for regular sales."""
        regular = self.get_regular(period)
        cat = regular.groupby("category_clean").agg(
            revenue=("actual_revenue", "sum"),
            cost=("cost", "sum"),
        ).reset_index()
        cat["margin"] = ((cat["revenue"] - cat["cost"]) / cat["revenue"].replace(0, float("nan")) * 100).round(1)
        return dict(zip(cat["category_clean"], cat["margin"]))

    def brand_category_rankings(self, period: PeriodFilter | None = None) -> pd.DataFrame:
        """Revenue rankings per brand within each category."""
        regular = self.get_regular(period)
        bcr = regular.groupby(["category_clean", "brand_clean"])["actual_revenue"].sum().reset_index()
        bcr["rank"] = bcr.groupby("category_clean")["actual_revenue"].rank(ascending=False, method="min")
        bcr["total_brands"] = bcr.groupby("category_clean")["brand_clean"].transform("count")
        return bcr
