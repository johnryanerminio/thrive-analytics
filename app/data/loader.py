"""
Multi-month CSV discovery, loading, and deduplication.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from app.config import (
    INBOX_FOLDER, SALES_KEYWORDS, BT_PERFORMANCE_KEYWORDS, CUSTOMER_KEYWORDS,
    INTERNAL_BRAND_COSTS, COST_CORRECTION_YEARS, PRE_ROLL_CATEGORIES,
)
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
    exclude_keywords: list[str] | None = None,
) -> list[Path]:
    """Recursively find sales CSVs in inbox (including year subdirs)."""
    if keywords is None:
        keywords = SALES_KEYWORDS
        # When using default sales keywords, exclude BT and customer files
        exclude_keywords = BT_PERFORMANCE_KEYWORDS + CUSTOMER_KEYWORDS

    matches: list[Path] = []
    if not inbox.exists():
        return matches

    for csv_file in inbox.rglob("*.csv"):
        filename_lower = csv_file.name.lower()
        if exclude_keywords and any(ex in filename_lower for ex in exclude_keywords):
            continue
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
    """Load one CSV, normalise columns and categories, minimize memory."""
    # Only read columns we actually use
    from app.config import COLUMN_MAP
    usecols = [c for c in COLUMN_MAP.keys()]
    try:
        df = pd.read_csv(filepath, usecols=lambda c: c in usecols)
    except Exception:
        df = pd.read_csv(filepath)  # fallback if columns don't match
    df = normalize_columns(df)
    df = normalize_categories(df)

    # Convert strings to category early to save memory during concat
    for col in ["brand_clean", "store_clean", "category_clean", "product"]:
        if col in df.columns:
            df[col] = df[col].astype("category")

    # Tag with source file metadata for dedup ordering
    _, end_date = _parse_file_dates(filepath)
    df["_source_file"] = filepath.name
    df["_source_end_date"] = end_date or "0000-00-00"

    return df


def apply_internal_cost_corrections(df: pd.DataFrame) -> pd.DataFrame:
    """Correct cost data for internal brands where Flowhub cost is unreliable.

    2024: Replace cost only when cost_per_item < $1/unit (was $0 or pennies).
    2025: Replace ALL costs (were inflated/inaccurate).
    2026+: No changes — costs are accurate.
    """
    if df.empty or "year" not in df.columns:
        return df

    total_corrected = 0
    is_preroll = df["category_clean"].isin(PRE_ROLL_CATEGORIES)

    for brand_upper, prices in INTERNAL_BRAND_COSTS.items():
        brand_mask = df["brand_clean"].str.upper() == brand_upper

        for year_val, mode in COST_CORRECTION_YEARS.items():
            year_mask = brand_mask & (df["year"] == year_val)
            if mode == "conditional":
                year_mask = year_mask & (df["cost_per_item"] < 1.0)

            count = year_mask.sum()
            if count == 0:
                continue

            # Apply per-unit cost: pre-roll categories get $4, others get default
            new_cost_per_unit = pd.Series(prices["default"], index=df.index)
            new_cost_per_unit = new_cost_per_unit.where(~is_preroll, prices["pre_roll"])

            df.loc[year_mask, "cost"] = df.loc[year_mask, "quantity"] * new_cost_per_unit[year_mask]
            df.loc[year_mask, "cost_per_item"] = new_cost_per_unit[year_mask]
            df.loc[year_mask, "net_profit"] = df.loc[year_mask, "actual_revenue"] - df.loc[year_mask, "cost"]

            total_corrected += count
            print(f"  Cost correction: {brand_upper} {year_val} ({mode}) — {count:,} rows adjusted")

    if total_corrected:
        print(f"  Total cost corrections: {total_corrected:,} rows across {len(INTERNAL_BRAND_COSTS)} brands")

    return df


def load_all_csvs(
    inbox: Path = INBOX_FOLDER,
    keywords: list[str] | None = None,
) -> pd.DataFrame:
    """Discover all sales CSVs, load incrementally, and deduplicate.

    Processes one CSV at a time to minimize peak memory usage.
    Deduplication key: (receipt_id, product, completed_at).
    When CSVs overlap, keep the row from the most recently exported file.
    """
    import gc

    files = discover_csvs(inbox, keywords)
    if not files:
        return pd.DataFrame()

    # Incremental loading: process one file at a time, concat in pairs
    # This avoids having all individual DataFrames in memory simultaneously
    df = None
    total_loaded = 0
    file_count = 0
    for f in files:
        try:
            chunk = load_single_csv(f)
            total_loaded += len(chunk)
            file_count += 1
            if df is None:
                df = chunk
            else:
                df = pd.concat([df, chunk], ignore_index=True)
                del chunk
                gc.collect()
        except Exception as exc:
            print(f"  Warning: skipping {f.name}: {exc}")

    if df is None or df.empty:
        return pd.DataFrame()

    # Dedup: sort by source end-date desc so most-recent file wins
    df = df.sort_values("_source_end_date", ascending=False)
    df = df.drop_duplicates(subset=["receipt_id", "product", "completed_at"], keep="first")
    post_dedup = len(df)
    gc.collect()

    print(f"  Loaded {total_loaded:,} rows from {file_count} files, {total_loaded - post_dedup:,} duplicates removed → {post_dedup:,} unique rows")

    # Classify transactions (vectorized for speed and memory)
    df["transaction_type"] = _classify_transactions_vectorized(df)
    df["deal_type"] = _classify_deal_types_vectorized(df)

    # Apply internal brand cost corrections (2024 + 2025)
    df = apply_internal_cost_corrections(df)

    # Drop columns no longer needed to save memory
    drop_cols = ["_source_file", "_source_end_date", "product_clean", "deals_upper"]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])

    return df


def _classify_transactions_vectorized(df: pd.DataFrame) -> pd.Series:
    """Vectorized transaction classification — much faster than row-by-row apply."""
    deals = df["deals_upper"].fillna("")
    product = df.get("product_clean", pd.Series("", index=df.index)).fillna("")
    actual_rev = df["actual_revenue"].fillna(0)

    result = pd.Series("REGULAR", index=df.index)
    result[deals.str.contains("REWARD|POINT|REDEMPTION", regex=True, na=False)] = "REWARD"
    result[deals.str.contains("MARKOUT|MARK OUT|MARK-OUT", regex=True, na=False)] = "MARKOUT"
    result[product.str.contains("TESTER", na=False) | deals.str.contains("TESTER", na=False)] = "TESTER"
    result[(actual_rev <= 1.00) & ~product.str.contains("EXIT BAG", na=False) & (result == "REGULAR")] = "COMP"
    return result


def _classify_deal_types_vectorized(df: pd.DataFrame) -> pd.Series:
    """Vectorized deal type classification."""
    deals = df["deals_upper"].fillna("")
    inline = df.get("inline_discounts", pd.Series("", index=df.index)).fillna("").astype(str).str.upper()
    combined = deals + " " + inline

    result = pd.Series("OTHER", index=df.index)
    result[(deals == "") & (inline == "")] = "NO DEAL"
    result[combined.str.contains("B1G|B2G|BOGO|2 FOR|3 FOR|4 FOR|5 FOR|2/\\$|3/\\$|4/\\$|5/\\$", regex=True, na=False)] = "BUNDLE"
    result[combined.str.contains("%|PERCENT", regex=True, na=False) & (result == "OTHER")] = "PERCENT OFF"
    result[combined.str.contains("SENIOR|VETERAN|MILITARY|MEDICAL|INDUSTRY|VIP|EMPLOYEE", regex=True, na=False) & (result == "OTHER")] = "CUSTOMER DISCOUNT"
    result[combined.str.contains("FOR \\$|FOR\\$", regex=True, na=False) & (result == "OTHER")] = "PRICE DEAL"
    return result


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
