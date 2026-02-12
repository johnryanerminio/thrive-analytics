"""
Column mapping, category normalization, transaction/deal classification.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from app.config import COLUMN_MAP, CURRENCY_COLS, CATEGORY_NORMALIZATION, CUSTOMER_SEGMENTS


# ---------------------------------------------------------------------------
# Column normalisation
# ---------------------------------------------------------------------------

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename raw Flowhub columns, parse types, add derived columns."""
    df = df.rename(columns=COLUMN_MAP)

    # Currency columns → float
    for col in CURRENCY_COLS:
        if col in df.columns:
            df[col] = df[col].replace(r"[\$,]", "", regex=True).astype(float)

    # Datetime
    df["completed_at"] = pd.to_datetime(
        df["completed_at"], format="%m/%d/%Y %I:%M:%S %p", errors="coerce"
    )
    df["sale_date"] = df["completed_at"].dt.date
    df = df.dropna(subset=["completed_at"])

    # Clean strings
    df["store_clean"] = df["store"].str.replace(r" - RD\d+", "", regex=True).str.strip()
    df["brand_clean"] = df["brand"].str.strip()
    if "category" in df.columns:
        df["category_clean"] = df["category"].str.strip().str.upper()
    else:
        df["category_clean"] = "UNKNOWN"
    if "product" in df.columns:
        df["product_clean"] = df["product"].str.strip().str.upper()
    else:
        df["product_clean"] = ""

    # Deal helpers
    df["deals_upper"] = df["deals_used"].fillna("").str.upper()
    df["has_discount"] = df["discounts"] > 0

    # Year/month for period grouping
    df["year"] = df["completed_at"].dt.year
    df["month"] = df["completed_at"].dt.month
    df["year_month"] = df["completed_at"].dt.to_period("M")

    return df


# ---------------------------------------------------------------------------
# Category normalization
# ---------------------------------------------------------------------------

def normalize_categories(df: pd.DataFrame) -> pd.DataFrame:
    """Map variant category aliases to canonical names."""
    df["category_clean"] = df["category_clean"].replace(CATEGORY_NORMALIZATION)
    return df


# ---------------------------------------------------------------------------
# Transaction classification
# ---------------------------------------------------------------------------

def classify_transaction(row: pd.Series) -> str:
    """Classify a row as REGULAR, REWARD, MARKOUT, TESTER, or COMP."""
    deals = str(row.get("deals_upper", ""))
    product = str(row.get("product_clean", ""))
    actual_rev = row.get("actual_revenue", 0)

    if "REWARD" in deals or "POINT" in deals or "REDEMPTION" in deals:
        return "REWARD"
    if "MARKOUT" in deals or "MARK OUT" in deals or "MARK-OUT" in deals:
        return "MARKOUT"
    if "TESTER" in product or "TESTER" in deals:
        return "TESTER"
    if actual_rev <= 1.00 and "EXIT BAG" not in product:
        return "COMP"
    return "REGULAR"


def classify_deal_type(row: pd.Series) -> str:
    """Classify the deal type for a transaction row."""
    deals = str(row.get("deals_upper", ""))
    inline = str(row.get("inline_discounts", "")).upper() if pd.notna(row.get("inline_discounts")) else ""

    if not deals and not inline:
        return "NO DEAL"
    combined = deals + " " + inline

    if any(x in combined for x in ["B1G", "B2G", "BOGO", "2 FOR", "3 FOR", "4 FOR", "5 FOR", "2/$", "3/$", "4/$", "5/$"]):
        return "BUNDLE"
    if "%" in combined or "PERCENT" in combined:
        return "PERCENT OFF"
    if any(x in combined for x in ["SENIOR", "VETERAN", "MILITARY", "MEDICAL", "INDUSTRY", "VIP", "EMPLOYEE"]):
        return "CUSTOMER DISCOUNT"
    if "FOR $" in combined or "FOR$" in combined:
        return "PRICE DEAL"
    return "OTHER"


# ---------------------------------------------------------------------------
# Customer segmentation
# ---------------------------------------------------------------------------

def get_customer_segment(groups: str) -> str:
    """Return the customer segment based on group membership string."""
    if pd.isna(groups) or groups == "":
        return "Regular"
    groups_upper = str(groups).upper()
    for keyword, segment in CUSTOMER_SEGMENTS:
        if keyword in groups_upper:
            return segment
    return "Other Group"


# ---------------------------------------------------------------------------
# Reward name extraction
# ---------------------------------------------------------------------------

def extract_reward_name(deals_str: str) -> str | None:
    """Pull the reward description from a deals string."""
    if pd.isna(deals_str):
        return None
    match = re.search(
        r"(REWARD\s*-\s*\d+\s*Points?\s*-\s*[^,]+)", str(deals_str), re.IGNORECASE
    )
    if match:
        return match.group(1).strip()
    if "REWARD" in str(deals_str).upper():
        return str(deals_str).strip()
    return None
