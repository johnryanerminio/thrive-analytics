"""
Customer analytics — unique counts, segmentation, per-customer metrics.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics.common import safe_divide
from app.data.normalize import get_customer_segment


def customer_metrics(
    sales_df: pd.DataFrame,
    cust_attr_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Compute per-customer metrics from period sales data."""
    # Filter to regular sales
    regular = sales_df[sales_df["transaction_type"] == "REGULAR"].copy()

    cust = regular.groupby("customer_id").agg(
        customer_name=("customer_name", "first"),
        transactions=("receipt_id", "nunique"),
        total_spent=("actual_revenue", "sum"),
        total_discounts=("discounts", "sum"),
        total_units=("quantity", "sum"),
        primary_store=("store_clean", lambda x: x.value_counts().index[0] if len(x) > 0 else "Unknown"),
    ).reset_index()

    # Average transaction value
    txn_totals = regular.groupby(["customer_id", "receipt_id"])["actual_revenue"].sum().reset_index()
    avg_txn = txn_totals.groupby("customer_id")["actual_revenue"].mean().reset_index()
    avg_txn.columns = ["customer_id", "avg_transaction"]
    cust = cust.merge(avg_txn, on="customer_id", how="left")

    # Discount rate
    cust["discount_rate"] = (
        cust["total_discounts"]
        / (cust["total_spent"] + cust["total_discounts"]).replace(0, np.nan)
        * 100
    ).round(1)

    # Merge customer attributes
    if cust_attr_df is not None and "customer_id" in cust_attr_df.columns:
        merge_cols = ["customer_id"]
        if "groups" in cust_attr_df.columns:
            merge_cols.append("groups")
        if "is_loyal" in cust_attr_df.columns:
            merge_cols.append("is_loyal")
        cust = cust.merge(cust_attr_df[merge_cols], on="customer_id", how="left")
    else:
        cust["groups"] = ""
        cust["is_loyal"] = "No"

    cust["segment"] = cust["groups"].apply(get_customer_segment)
    return cust


def customer_summary(sales_df: pd.DataFrame, cust_attr_df: pd.DataFrame | None = None) -> dict:
    """Company-wide customer KPIs."""
    regular = sales_df[sales_df["transaction_type"] == "REGULAR"]
    total_rev = regular["actual_revenue"].sum()
    total_disc = regular["discounts"].sum()
    total_trans = regular["receipt_id"].nunique()
    total_cust = regular["customer_id"].nunique()

    cust = customer_metrics(sales_df, cust_attr_df)
    loyalty_cust = (cust["is_loyal"] == "Yes").sum() if "is_loyal" in cust.columns else 0

    return {
        "total_customers": int(total_cust),
        "total_revenue": float(total_rev),
        "revenue_per_customer": round(safe_divide(total_rev, total_cust), 2),
        "loyalty_rate": round(safe_divide(loyalty_cust, total_cust) * 100, 1),
        "total_transactions": int(total_trans),
        "avg_transaction": round(safe_divide(total_rev, total_trans), 2),
        "total_discounts": float(total_disc),
        "discount_rate": round(safe_divide(total_disc, total_rev + total_disc) * 100, 1),
    }


def segment_summary(cust_df: pd.DataFrame, total_revenue: float) -> list[dict]:
    """Revenue and customer counts by segment."""
    total_cust = len(cust_df)
    seg = cust_df.groupby("segment").agg(
        customers=("customer_id", "count"),
        total_revenue=("total_spent", "sum"),
        total_discounts=("total_discounts", "sum"),
    ).reset_index()

    seg["rev_per_cust"] = (seg["total_revenue"] / seg["customers"]).round(2)
    seg["discount_rate"] = (seg["total_discounts"] / (seg["total_revenue"] + seg["total_discounts"]).replace(0, np.nan) * 100).round(1)
    seg["pct_of_cust"] = (seg["customers"] / total_cust * 100).round(1)
    seg["pct_of_rev"] = (seg["total_revenue"] / total_revenue * 100).round(1) if total_revenue > 0 else 0
    seg = seg.sort_values("total_revenue", ascending=False)

    return seg.fillna(0).to_dict("records")


def top_customers(cust_df: pd.DataFrame, n: int = 50) -> list[dict]:
    """Top N customers by spend."""
    top = cust_df.nlargest(n, "total_spent").copy()
    top["rank"] = range(1, len(top) + 1)
    return top.fillna(0).to_dict("records")


def brand_customer_count(brand_df: pd.DataFrame) -> int:
    """Unique customers for a brand."""
    return brand_df["customer_id"].nunique()
