"""
Multi-month CSV discovery, loading, and deduplication.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from app.config import INBOX_FOLDER, SALES_KEYWORDS, BT_PERFORMANCE_KEYWORDS, CUSTOMER_KEYWORDS
from app.data.normalize import normalize_columns, normalize_categories, classify_transaction, classify_deal_type


# ---------------------------------------------------------------------------
# Date-range extraction from filenames
# ---------------------------------------------------------------------------

_DATE_RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{4}-\d{2}-\d{2})")


def _parse_file_dates(filepath: Path) -> tuple[str | None, str | None]:
    """Extract (start_date, end_date) strings from a filename like
    "John's Margin Report 2025-01-01 2025-01-31.csv"
    """
    m = _DATE_RANGE_RE.search(filepath.stem)
    if m:
        return m.group(1), m.group(2)
    return None, None


# ---------------------------------------------------------------------------
# CSV discovery
# ---------------------------------------------------------------------------

def discover_csvs(
    inbox: Path = INBOX_FOLDER,
    keywords: list[str] | None = None,
) -> list[Path]:
    """Recursively find sales CSVs in inbox (including year subdirs)."""
    if keywords is None:
        keywords = SALES_KEYWORDS

    matches: list[Path] = []
    if not inbox.exists():
        return matches

    for csv_file in inbox.rglob("*.csv"):
        filename_lower = csv_file.name.lower()
        if any(kw in filename_lower for kw in keywords):
            matches.append(csv_file)

    # Sort by file end-date descending (most recent export first)
    def _sort_key(p: Path) -> str:
        _, end = _parse_file_dates(p)
        return end or "0000-00-00"

    matches.sort(key=_sort_key, reverse=True)
    return matches


def discover_bt_csvs(inbox: Path = INBOX_FOLDER) -> list[Path]:
    """Find budtender performance CSVs."""
    return discover_csvs(inbox, BT_PERFORMANCE_KEYWORDS)


def discover_customer_csvs(inbox: Path = INBOX_FOLDER) -> list[Path]:
    """Find customer attribute CSVs."""
    return discover_csvs(inbox, CUSTOMER_KEYWORDS)


# ---------------------------------------------------------------------------
# Loading & dedup
# ---------------------------------------------------------------------------

def load_single_csv(filepath: Path) -> pd.DataFrame:
    """Load one CSV, normalise columns and categories."""
    df = pd.read_csv(filepath)
    df = normalize_columns(df)
    df = normalize_categories(df)

    # Tag with source file metadata for dedup ordering
    _, end_date = _parse_file_dates(filepath)
    df["_source_file"] = filepath.name
    df["_source_end_date"] = end_date or "0000-00-00"

    return df


def load_all_csvs(
    inbox: Path = INBOX_FOLDER,
    keywords: list[str] | None = None,
) -> pd.DataFrame:
    """Discover all sales CSVs, load, concatenate, and deduplicate.

    Deduplication key: (receipt_id, product, completed_at).
    When CSVs overlap, keep the row from the most recently exported file.
    """
    files = discover_csvs(inbox, keywords)
    if not files:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for f in files:
        try:
            frames.append(load_single_csv(f))
        except Exception as exc:
            print(f"  Warning: skipping {f.name}: {exc}")

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)

    # Dedup: sort by source end-date desc so most-recent file wins
    pre_dedup = len(df)
    df = df.sort_values("_source_end_date", ascending=False)
    df = df.drop_duplicates(subset=["receipt_id", "product", "completed_at"], keep="first")
    post_dedup = len(df)

    print(f"  Loaded {pre_dedup:,} rows from {len(files)} files, {pre_dedup - post_dedup:,} duplicates removed → {post_dedup:,} unique rows")

    # Classify transactions
    df["transaction_type"] = df.apply(classify_transaction, axis=1)
    df["deal_type"] = df.apply(classify_deal_type, axis=1)

    # Drop internal dedup columns
    df = df.drop(columns=["_source_file", "_source_end_date"])

    return df


# ---------------------------------------------------------------------------
# Budtender / Customer loading
# ---------------------------------------------------------------------------

def load_bt_performance(filepath: Path) -> pd.DataFrame:
    """Load a budtender performance CSV."""
    df = pd.read_csv(filepath)
    currency_cols = ["Average Cart Value (pre-tax)", "Sales (pre-tax)", "Upsell Total Price", "Upsell Total Profit"]
    for col in currency_cols:
        if col in df.columns:
            df[col] = df[col].replace(r"[\$,]", "", regex=True).astype(float)
    if "% of Sales Discounted" in df.columns:
        df["% of Sales Discounted"] = df["% of Sales Discounted"].replace(r"%", "", regex=True).astype(float)
    return df


def load_customer_attributes(filepath: Path) -> pd.DataFrame:
    """Load a customer attributes CSV."""
    df = pd.read_csv(filepath)
    col_map = {
        "ID": "customer_id",
        "Name": "customer_name",
        "Groups": "groups",
        "Loyal": "is_loyal",
        "Loyalty Points": "loyalty_points",
    }
    df = df.rename(columns=col_map)
    return df
