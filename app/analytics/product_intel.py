"""
Product Intelligence analytics — ABC classification, dead stock detection,
and velocity trend analysis.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from app.analytics.common import safe_divide, sanitize_for_json


def product_intelligence(regular_df: pd.DataFrame) -> dict:
    """Analyse regular transactions and return product intelligence metrics.

    Parameters
    ----------
    regular_df : pd.DataFrame
        Regular transactions with columns: product, actual_revenue, net_profit,
        quantity, cost, sale_date, store_clean, category_clean, brand_clean

    Returns
    -------
    dict with keys: kpis, abc_products, dead_stock, accelerating, decelerating
    """
    empty_result = {
        "kpis": {
            "total_products": 0,
            "a_count": 0,
            "b_count": 0,
            "c_count": 0,
            "d_count": 0,
            "a_revenue_pct": 0.0,
            "dead_stock_count": 0,
            "dead_stock_revenue": 0.0,
            "accelerating_count": 0,
            "decelerating_count": 0,
        },
        "abc_products": [],
        "dead_stock": [],
        "accelerating": [],
        "decelerating": [],
    }

    if regular_df is None or regular_df.empty:
        return sanitize_for_json(empty_result)

    df = regular_df.copy()
    df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")
    df = df.dropna(subset=["sale_date"])

    if df.empty:
        return sanitize_for_json(empty_result)

    # ------------------------------------------------------------------
    # ABC Classification
    # ------------------------------------------------------------------
    abc_products, class_counts, a_revenue_pct = _abc_classification(df)

    # ------------------------------------------------------------------
    # Dead Stock Detection
    # ------------------------------------------------------------------
    dead_stock = _dead_stock_detection(df)

    # ------------------------------------------------------------------
    # Velocity Trends
    # ------------------------------------------------------------------
    accelerating, decelerating = _velocity_trends(df)

    # ------------------------------------------------------------------
    # KPIs
    # ------------------------------------------------------------------
    total_products = df["product"].nunique()
    dead_stock_count = len(dead_stock)
    dead_stock_revenue = sum(p["total_revenue"] for p in dead_stock)

    kpis = {
        "total_products": total_products,
        "a_count": class_counts.get("A", 0),
        "b_count": class_counts.get("B", 0),
        "c_count": class_counts.get("C", 0),
        "d_count": class_counts.get("D", 0),
        "a_revenue_pct": round(a_revenue_pct, 1),
        "dead_stock_count": dead_stock_count,
        "dead_stock_revenue": round(dead_stock_revenue, 2),
        "accelerating_count": len(accelerating),
        "decelerating_count": len(decelerating),
    }

    result = {
        "kpis": kpis,
        "abc_products": abc_products,
        "dead_stock": dead_stock,
        "accelerating": accelerating,
        "decelerating": decelerating,
    }

    return sanitize_for_json(result)


# ======================================================================
# Internal helpers
# ======================================================================


def _abc_classification(df: pd.DataFrame) -> tuple[list, dict, float]:
    """Return (abc_products list, class_counts dict, a_revenue_pct)."""
    product_stats = (
        df.groupby("product", sort=False)
        .agg(
            profit=("net_profit", "sum"),
            revenue=("actual_revenue", "sum"),
            cost=("cost", "sum"),
            units=("quantity", "sum"),
            brand=("brand_clean", "first"),
            category=("category_clean", "first"),
        )
        .reset_index()
    )

    # Sort by profit descending; products with zero/negative profit go to the end
    product_stats = product_stats.sort_values("profit", ascending=False).reset_index(drop=True)

    total_profit = product_stats["profit"].clip(lower=0).sum()

    if total_profit <= 0:
        # All products have zero or negative profit — assign D to everything
        product_stats["abc_class"] = "D"
        product_stats["cumulative_pct"] = 0.0
    else:
        # Only positive-profit products contribute to cumulative %
        clipped = product_stats["profit"].clip(lower=0)
        product_stats["cumulative_pct"] = (clipped.cumsum() / total_profit * 100)

        def _classify(cum_pct: float, profit: float) -> str:
            if profit <= 0:
                return "D"
            if cum_pct <= 80:
                return "A"
            if cum_pct <= 95:
                return "B"
            if cum_pct <= 99:
                return "C"
            return "D"

        product_stats["abc_class"] = [
            _classify(cp, p)
            for cp, p in zip(product_stats["cumulative_pct"], product_stats["profit"])
        ]

    class_counts = product_stats["abc_class"].value_counts().to_dict()

    # A-class revenue percentage
    total_revenue = product_stats["revenue"].sum()
    a_revenue = product_stats.loc[product_stats["abc_class"] == "A", "revenue"].sum()
    a_revenue_pct = safe_divide(a_revenue, total_revenue) * 100

    # Build output list (top 100)
    top = product_stats.head(100)
    abc_products = []
    for _, row in top.iterrows():
        margin = safe_divide(row["profit"], row["revenue"]) * 100
        abc_products.append(
            {
                "product": row["product"],
                "brand": row["brand"],
                "category": row["category"],
                "revenue": round(float(row["revenue"]), 2),
                "profit": round(float(row["profit"]), 2),
                "margin": round(margin, 1),
                "units": int(row["units"]),
                "abc_class": row["abc_class"],
                "cumulative_pct": round(float(row["cumulative_pct"]), 1),
            }
        )

    return abc_products, class_counts, a_revenue_pct


def _dead_stock_detection(df: pd.DataFrame) -> list:
    """Detect products with no sales in the last 60 days."""
    max_date = df["sale_date"].max()
    cutoff = max_date - pd.Timedelta(days=60)

    all_stores = set(df["store_clean"].unique())

    product_last_sale = (
        df.groupby("product", sort=False)
        .agg(
            last_sale_date=("sale_date", "max"),
            total_revenue=("actual_revenue", "sum"),
            brand=("brand_clean", "first"),
            category=("category_clean", "first"),
        )
        .reset_index()
    )

    # Global dead stock: last sale before cutoff
    dead = product_last_sale[product_last_sale["last_sale_date"] < cutoff].copy()

    if dead.empty:
        return []

    dead["days_since_sale"] = (max_date - dead["last_sale_date"]).dt.days

    # Per-store activity: which stores sold each product in the recent window
    recent = df[df["sale_date"] >= cutoff]
    if not recent.empty:
        recent_stores = recent.groupby("product")["store_clean"].apply(set).to_dict()
    else:
        recent_stores = {}

    # All-time stores per product
    all_time_stores = df.groupby("product")["store_clean"].apply(set).to_dict()

    dead_list = []
    dead = dead.sort_values("total_revenue", ascending=False).head(50)

    for _, row in dead.iterrows():
        prod = row["product"]
        active = recent_stores.get(prod, set())
        product_stores = all_time_stores.get(prod, set())
        inactive = product_stores - active

        dead_list.append(
            {
                "product": prod,
                "brand": row["brand"],
                "category": row["category"],
                "last_sale_date": row["last_sale_date"].strftime("%Y-%m-%d"),
                "days_since_sale": int(row["days_since_sale"]),
                "total_revenue": round(float(row["total_revenue"]), 2),
                "stores_active": len(active),
                "stores_inactive": len(inactive),
            }
        )

    return dead_list


def _velocity_trends(df: pd.DataFrame) -> tuple[list, list]:
    """Compare units/day in the most recent 3 months vs prior 3 months."""
    max_date = df["sale_date"].max()
    recent_start = max_date - pd.Timedelta(days=90)
    prior_start = recent_start - pd.Timedelta(days=90)

    # Need at least some data in both windows
    recent_df = df[df["sale_date"] >= recent_start]
    prior_df = df[(df["sale_date"] >= prior_start) & (df["sale_date"] < recent_start)]

    if recent_df.empty or prior_df.empty:
        return [], []

    recent_days = max((max_date - recent_start).days, 1)
    prior_days = max((recent_start - prior_start).days, 1)

    recent_vel = (
        recent_df.groupby("product", sort=False)
        .agg(
            units=("quantity", "sum"),
            brand=("brand_clean", "first"),
            category=("category_clean", "first"),
        )
        .reset_index()
    )
    recent_vel["recent_velocity"] = recent_vel["units"] / recent_days

    prior_vel = (
        prior_df.groupby("product", sort=False)["quantity"]
        .sum()
        .reset_index()
        .rename(columns={"quantity": "prior_units"})
    )
    prior_vel["prior_velocity"] = prior_vel["prior_units"] / prior_days

    merged = recent_vel.merge(prior_vel[["product", "prior_velocity"]], on="product", how="inner")

    # Only include products that had meaningful prior velocity
    merged = merged[merged["prior_velocity"] > 0].copy()

    if merged.empty:
        return [], []

    merged["change_pct"] = (
        (merged["recent_velocity"] - merged["prior_velocity"])
        / merged["prior_velocity"]
        * 100
    )

    def _to_records(subset: pd.DataFrame) -> list:
        records = []
        for _, row in subset.iterrows():
            records.append(
                {
                    "product": row["product"],
                    "brand": row["brand"],
                    "category": row["category"],
                    "recent_velocity": round(float(row["recent_velocity"]), 3),
                    "prior_velocity": round(float(row["prior_velocity"]), 3),
                    "change_pct": round(float(row["change_pct"]), 1),
                }
            )
        return records

    accel = merged.nlargest(20, "change_pct")
    accel = accel[accel["change_pct"] > 0]

    decel = merged.nsmallest(20, "change_pct")
    decel = decel[decel["change_pct"] < 0]

    return _to_records(accel), _to_records(decel)
