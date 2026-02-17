"""
Velocity analytics — units/day, share-of-category, trends, benchmarking.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics.common import safe_divide, pct_change


def velocity_metrics(brand_df: pd.DataFrame, all_regular_df: pd.DataFrame) -> dict:
    """Compute velocity KPIs for a brand vs category averages."""
    if brand_df.empty:
        return {}

    days = max((brand_df["sale_date"].max() - brand_df["sale_date"].min()).days + 1, 1)
    total_days = max((all_regular_df["sale_date"].max() - all_regular_df["sale_date"].min()).days + 1, 1)

    brand_units = brand_df["quantity"].sum()
    brand_revenue = brand_df["actual_revenue"].sum()
    brand_transactions = brand_df["receipt_id"].nunique()

    return {
        "units_per_day": round(safe_divide(brand_units, days), 2),
        "revenue_per_day": round(safe_divide(brand_revenue, days), 2),
        "avg_units_per_txn": round(safe_divide(brand_units, brand_transactions), 2),
        "days_of_data": days,
        "total_units": int(brand_units),
        "total_transactions": int(brand_transactions),
    }


def velocity_by_category(
    brand_df: pd.DataFrame,
    all_regular_df: pd.DataFrame,
) -> list[dict]:
    """Brand velocity vs category average per category."""
    if brand_df.empty:
        return []

    days = max((all_regular_df["sale_date"].max() - all_regular_df["sale_date"].min()).days + 1, 1)
    results = []

    for cat in brand_df["category_clean"].unique():
        brand_cat = brand_df[brand_df["category_clean"] == cat]
        all_cat = all_regular_df[all_regular_df["category_clean"] == cat]

        brand_units_day = safe_divide(brand_cat["quantity"].sum(), days)

        # Category average per brand
        n_brands = all_cat["brand_clean"].nunique()
        cat_units_day = safe_divide(all_cat["quantity"].sum(), days)
        avg_brand_units_day = safe_divide(cat_units_day, n_brands) if n_brands > 0 else 0

        brand_rev_unit = safe_divide(brand_cat["actual_revenue"].sum(), brand_cat["quantity"].sum())
        cat_rev_unit = safe_divide(all_cat["actual_revenue"].sum(), all_cat["quantity"].sum())

        results.append({
            "category": cat,
            "brand_units_per_day": round(brand_units_day, 2),
            "category_avg_units_per_day": round(avg_brand_units_day, 2),
            "velocity_index": round(safe_divide(brand_units_day, avg_brand_units_day) * 100, 1) if avg_brand_units_day > 0 else 0,
            "brand_rev_per_unit": round(brand_rev_unit, 2),
            "category_rev_per_unit": round(cat_rev_unit, 2),
            "brands_in_category": n_brands,
        })

    return sorted(results, key=lambda x: x.get("velocity_index", 0), reverse=True)


def share_of_category(
    brand_df: pd.DataFrame,
    all_regular_df: pd.DataFrame,
) -> list[dict]:
    """Brand's percentage of category revenue."""
    if brand_df.empty:
        return []

    results = []
    for cat in brand_df["category_clean"].unique():
        brand_rev = brand_df[brand_df["category_clean"] == cat]["actual_revenue"].sum()
        cat_rev = all_regular_df[all_regular_df["category_clean"] == cat]["actual_revenue"].sum()
        brand_units = brand_df[brand_df["category_clean"] == cat]["quantity"].sum()
        cat_units = all_regular_df[all_regular_df["category_clean"] == cat]["quantity"].sum()

        results.append({
            "category": cat,
            "brand_revenue": float(brand_rev),
            "category_revenue": float(cat_rev),
            "revenue_share_pct": round(safe_divide(brand_rev, cat_rev) * 100, 1),
            "brand_units": int(brand_units),
            "category_units": int(cat_units),
            "units_share_pct": round(safe_divide(brand_units, cat_units) * 100, 1),
        })

    return sorted(results, key=lambda x: x["brand_revenue"], reverse=True)


def monthly_trend(brand_df: pd.DataFrame) -> list[dict]:
    """Monthly revenue, margin, units with MoM change indicators."""
    if brand_df.empty:
        return []

    monthly = brand_df.groupby("year_month", observed=True).agg(
        revenue=("actual_revenue", "sum"),
        cost=("cost", "sum"),
        units=("quantity", "sum"),
        transactions=("receipt_id", "nunique"),
        profit=("net_profit", "sum"),
    ).sort_index()

    results = []
    prev = None
    for period, row in monthly.iterrows():
        margin = safe_divide(row["revenue"] - row["cost"], row["revenue"]) * 100

        entry = {
            "period": str(period),
            "revenue": float(row["revenue"]),
            "cost": float(row["cost"]),
            "margin": round(margin, 1),
            "units": int(row["units"]),
            "transactions": int(row["transactions"]),
            "profit": float(row["profit"]),
        }

        if prev is not None:
            entry["revenue_change_pct"] = round(pct_change(row["revenue"], prev["revenue"]) or 0, 1)
            entry["units_change_pct"] = round(pct_change(row["units"], prev["units"]) or 0, 1)
            entry["margin_change_pts"] = round(margin - prev["margin"], 1)
        else:
            entry["revenue_change_pct"] = None
            entry["units_change_pct"] = None
            entry["margin_change_pts"] = None

        results.append(entry)
        prev = {"revenue": row["revenue"], "units": row["units"], "margin": margin}

    return results


def share_of_category_trend(
    brand_df: pd.DataFrame,
    all_regular_df: pd.DataFrame,
    category: str,
) -> list[dict]:
    """Monthly share-of-category trend for a specific category."""
    brand_monthly = brand_df[brand_df["category_clean"] == category].groupby("year_month", observed=True)["actual_revenue"].sum()
    cat_monthly = all_regular_df[all_regular_df["category_clean"] == category].groupby("year_month", observed=True)["actual_revenue"].sum()

    all_periods = sorted(set(brand_monthly.index) | set(cat_monthly.index))
    results = []
    for period in all_periods:
        brand_rev = brand_monthly.get(period, 0)
        cat_rev = cat_monthly.get(period, 0)
        results.append({
            "period": str(period),
            "brand_revenue": float(brand_rev),
            "category_revenue": float(cat_rev),
            "share_pct": round(safe_divide(brand_rev, cat_rev) * 100, 1),
        })
    return results
