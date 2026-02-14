"""
Deal analytics — expansion, classification, discount depth, promo lift.
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from app.analytics.common import safe_divide, calc_margin, fillna_numeric


def extract_deals(deals_str: str) -> list[str]:
    """Split a comma-separated deals string into individual deal names."""
    if pd.isna(deals_str) or deals_str == "":
        return []
    return [d.strip() for d in str(deals_str).split(",") if d.strip()]


def expand_deals(df: pd.DataFrame) -> pd.DataFrame:
    """Expand rows so each deal gets its own row, with revenue split evenly.

    Uses vectorized str.split + explode instead of row-by-row iteration.
    """
    if "deals_used" not in df.columns:
        return pd.DataFrame()

    has_deals = df[df["deals_used"].notna() & (df["deals_used"] != "") & (df["deals_used"].str.strip() != "")]
    if has_deals.empty:
        return pd.DataFrame()

    # Split deals into lists and compute counts
    split = has_deals["deals_used"].str.split(",").apply(lambda x: [d.strip() for d in x if d.strip()])
    deal_counts = split.apply(len)
    nonzero = deal_counts > 0
    has_deals = has_deals[nonzero]
    split = split[nonzero]
    deal_counts = deal_counts[nonzero]

    if has_deals.empty:
        return pd.DataFrame()

    # Explode: repeat each row by its deal count, then assign deal names
    exploded = has_deals.loc[has_deals.index.repeat(deal_counts)].copy()
    exploded["deal_name"] = [d for sublist in split for d in sublist]
    n_deals = exploded.index.map(deal_counts)

    # Rename to expected column names and split revenue evenly
    result = pd.DataFrame({
        "deal_name": exploded["deal_name"].values,
        "receipt_id": exploded["receipt_id"].values,
        "store": exploded["store_clean"].values if "store_clean" in exploded.columns else "",
        "brand": exploded["brand_clean"].values if "brand_clean" in exploded.columns else "",
        "category": exploded["category_clean"].values if "category_clean" in exploded.columns else "",
        "revenue": exploded["actual_revenue"].values / n_deals.values,
        "discounts": exploded["discounts"].values / n_deals.values,
        "quantity": exploded["quantity"].values / n_deals.values,
        "cost": exploded["cost"].values / n_deals.values,
        "profit": (exploded["net_profit"].values if "net_profit" in exploded.columns else 0) / n_deals.values,
        "pre_discount_revenue": (exploded["pre_discount_revenue"].values if "pre_discount_revenue" in exploded.columns else (exploded["actual_revenue"].values + exploded["discounts"].values)) / n_deals.values,
    })
    return result


def deal_summary(df: pd.DataFrame, top_n: int | None = None, _expanded: pd.DataFrame | None = None) -> list[dict]:
    """Summarize deals from expanded deal DataFrame."""
    if df.empty:
        return []

    expanded = _expanded if _expanded is not None else expand_deals(df)
    if expanded.empty:
        return []

    agg = expanded.groupby("deal_name").agg(
        times_used=("receipt_id", "nunique"),
        units=("quantity", "sum"),
        revenue=("revenue", "sum"),
        discounts=("discounts", "sum"),
        cost=("cost", "sum"),
        profit=("profit", "sum"),
        pre_discount_revenue=("pre_discount_revenue", "sum"),
    ).reset_index()

    agg["margin"] = ((agg["revenue"] - agg["cost"]) / agg["revenue"].replace(0, np.nan) * 100).round(1)
    agg["avg_discount"] = (agg["discounts"] / agg["pre_discount_revenue"].replace(0, np.nan) * 100).round(1)
    agg = agg.sort_values("times_used", ascending=False)

    if top_n:
        agg = agg.head(top_n)

    return fillna_numeric(agg).to_dict("records")


def deal_type_summary(regular_df: pd.DataFrame) -> list[dict]:
    """Performance breakdown by deal type classification."""
    agg = regular_df.groupby("deal_type").agg(
        transactions=("receipt_id", "nunique"),
        units=("quantity", "sum"),
        full_price_revenue=("pre_discount_revenue", "sum"),
        actual_revenue=("actual_revenue", "sum"),
        discounts=("discounts", "sum"),
        cost=("cost", "sum"),
        net_profit=("net_profit", "sum"),
    ).reset_index()

    agg["discount_rate"] = (agg["discounts"] / agg["full_price_revenue"].replace(0, np.nan) * 100).round(1)
    agg["margin"] = ((agg["actual_revenue"] - agg["cost"]) / agg["actual_revenue"].replace(0, np.nan) * 100).round(1)
    agg = agg.sort_values("actual_revenue", ascending=False)

    return fillna_numeric(agg).to_dict("records")


def deal_summary_by_store(df: pd.DataFrame, top_n: int = 10, _expanded: pd.DataFrame | None = None) -> dict[str, list[dict]]:
    """Top N deals per store."""
    expanded = _expanded if _expanded is not None else expand_deals(df)
    if expanded.empty:
        return {}

    result = {}
    for store in sorted(expanded["store"].dropna().unique()):
        store_data = expanded[expanded["store"] == store]
        agg = store_data.groupby("deal_name").agg(
            times_used=("receipt_id", "nunique"),
            units=("quantity", "sum"),
            revenue=("revenue", "sum"),
            discounts=("discounts", "sum"),
            cost=("cost", "sum"),
        ).reset_index()
        agg["margin"] = ((agg["revenue"] - agg["cost"]) / agg["revenue"].replace(0, np.nan) * 100).round(1)
        agg = agg.sort_values("times_used", ascending=False).head(top_n)
        result[store] = fillna_numeric(agg).to_dict("records")

    return result


def promo_lift(brand_df: pd.DataFrame) -> dict:
    """Compare discounted vs full-price velocity for a brand."""
    fp = brand_df[~brand_df["has_discount"]]
    disc = brand_df[brand_df["has_discount"]]

    fp_days = fp["sale_date"].nunique() if len(fp) > 0 else 1
    disc_days = disc["sale_date"].nunique() if len(disc) > 0 else 1

    fp_units_day = safe_divide(fp["quantity"].sum(), fp_days)
    disc_units_day = safe_divide(disc["quantity"].sum(), disc_days)

    return {
        "fp_units_per_day": round(fp_units_day, 2),
        "disc_units_per_day": round(disc_units_day, 2),
        "lift_pct": round(safe_divide(disc_units_day - fp_units_day, fp_units_day) * 100, 1) if fp_units_day > 0 else None,
        "fp_avg_revenue_per_unit": round(safe_divide(fp["actual_revenue"].sum(), fp["quantity"].sum()), 2),
        "disc_avg_revenue_per_unit": round(safe_divide(disc["actual_revenue"].sum(), disc["quantity"].sum()), 2),
    }
