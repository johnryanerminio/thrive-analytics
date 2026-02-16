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

def _downcast_numerics(df: pd.DataFrame) -> pd.DataFrame:
    """Downcast float64 → float32 and int64 → smaller ints to halve numeric RAM."""
    float32_cols = [
        "pre_discount_revenue", "discounts", "actual_revenue", "net_profit",
        "cost", "total_collected", "receipt_total", "cost_per_item", "taxes",
    ]
    for col in float32_cols:
        if col in df.columns:
            df[col] = df[col].astype("float32")

    if "year" in df.columns:
        df["year"] = df["year"].astype("int16")
    if "month" in df.columns:
        df["month"] = df["month"].astype("int8")
    if "quantity" in df.columns:
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype("int16")

    return df


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

    # Downcast numeric types to save ~50% on numeric columns
    df = _downcast_numerics(df)

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
            # Use float32 to match column dtype and avoid upcasting
            new_cost_per_unit = pd.Series(prices["default"], index=df.index, dtype="float32")
            new_cost_per_unit = new_cost_per_unit.where(~is_preroll, float(prices["pre_roll"]))

            new_cost = (df.loc[year_mask, "quantity"].astype("float32") * new_cost_per_unit[year_mask]).astype("float32")
            df.loc[year_mask, "cost"] = new_cost
            df.loc[year_mask, "cost_per_item"] = new_cost_per_unit[year_mask].astype("float32")
            df.loc[year_mask, "net_profit"] = (df.loc[year_mask, "actual_revenue"] - new_cost).astype("float32")

            total_corrected += count
            print(f"  Cost correction: {brand_upper} {year_val} ({mode}) — {count:,} rows adjusted")

    if total_corrected:
        print(f"  Total cost corrections: {total_corrected:,} rows across {len(INTERNAL_BRAND_COSTS)} brands")

    return df


_DEDUP_COLS = ["receipt_id", "product", "completed_at"]


def load_all_csvs(
    inbox: Path = INBOX_FOLDER,
    keywords: list[str] | None = None,
) -> pd.DataFrame:
    """Discover all sales CSVs, load incrementally, and deduplicate.

    Memory-optimised approach:
    - Files are sorted by end-date descending (most-recent first)
    - After each file concat, immediately dedup so the DataFrame never exceeds
      the unique-row count + one file chunk
    - No sort step needed — file processing order ensures keep='first' is correct
    - Numeric columns are float32, year/month are int16/int8
    """
    import gc

    files = discover_csvs(inbox, keywords)
    if not files:
        return pd.DataFrame()

    df = None
    total_loaded = 0
    file_count = 0
    for f in files:
        try:
            chunk = load_single_csv(f)
            rows = len(chunk)
            total_loaded += rows
            file_count += 1

            if df is None:
                df = chunk.drop_duplicates(subset=_DEDUP_COLS, keep="first")
                del chunk
                # Convert object columns to category to keep memory low
                for col in df.select_dtypes(include=["object"]).columns:
                    df[col] = df[col].astype("category")
                print(f"  [{file_count}/{len(files)}] {f.name}: {rows:,} rows → {len(df):,} unique")
            else:
                df = pd.concat([df, chunk], ignore_index=True)
                del chunk

                # Dedup immediately: rows already in df (from more-recent files) are kept
                pre = len(df)
                df = df.drop_duplicates(subset=_DEDUP_COLS, keep="first")
                dropped = pre - len(df)

                # Convert object columns to category to keep memory low
                for col in df.select_dtypes(include=["object"]).columns:
                    df[col] = df[col].astype("category")

                gc.collect()
                print(f"  [{file_count}/{len(files)}] {f.name}: +{rows:,}, dedup -{dropped:,} → {len(df):,} rows")

        except Exception as exc:
            print(f"  Warning: skipping {f.name}: {exc}")

    if df is None or df.empty:
        return pd.DataFrame()

    post_dedup = len(df)
    print(f"  Total: {total_loaded:,} raw rows from {file_count} files → {post_dedup:,} unique rows")

    # Drop completed_at — only needed for dedup, saves ~37 MB
    df = df.drop(columns=["completed_at"], errors="ignore")

    # Classification needs string ops on these columns; convert from category back to object
    for col in ["deals_upper", "product_clean", "inline_discounts"]:
        if col in df.columns and df[col].dtype.name == "category":
            df[col] = df[col].astype(object)

    # Classify transactions (vectorized for speed and memory)
    df["transaction_type"] = _classify_transactions_vectorized(df)
    df["deal_type"] = _classify_deal_types_vectorized(df)

    # Apply internal brand cost corrections (2024 + 2025)
    df = apply_internal_cost_corrections(df)

    # Drop columns no longer needed to save memory
    drop_cols = [
        "product_clean", "deals_upper",        # used only during classification
        "inline_discounts",                     # used only during deal classification
        "taxes", "total_collected", "receipt_total",  # never used in analytics/reports
        "brand", "category",                    # raw columns; analytics uses brand_clean/category_clean
    ]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])
    gc.collect()

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
