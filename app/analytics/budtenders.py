"""
Budtender analytics — sales score calculation, tiers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_sales_scores(
    bt_df: pd.DataFrame,
    sales_df: pd.DataFrame | None = None,
    min_transactions: int = 5,
) -> pd.DataFrame:
    """Calculate Sales Score (0-100) with tier classification."""
    bt = bt_df.rename(columns={
        "Name": "budtender",
        "Store": "store",
        "Average Cart Value (pre-tax)": "avg_cart_value",
        "Total Units Sold": "units_sold",
        "Average Units Per Cart": "avg_units_per_cart",
        "Number of Carts": "num_transactions",
        "Sales (pre-tax)": "total_sales",
        "% of Sales Discounted": "pct_sales_discounted",
        "Customers Enrolled In Loyalty": "loyalty_enrollments",
    })

    bt["store_clean"] = bt["store"].str.replace(r" - RD\d+", "", regex=True).str.strip()

    # Face-to-face %
    if sales_df is not None and "order_type" in sales_df.columns:
        f2f = sales_df.groupby("sold_by").apply(
            lambda x: (
                x["order_type"].str.upper().str.contains("WALK|IN-STORE|FACE", na=False).sum()
                / len(x) * 100
            ) if len(x) > 0 else 0,
            include_groups=False,
        ).reset_index()
        f2f.columns = ["budtender", "face_to_face_pct"]
        bt = bt.merge(f2f, on="budtender", how="left")
        bt["face_to_face_pct"] = bt["face_to_face_pct"].fillna(0)
    else:
        bt["face_to_face_pct"] = 0

    # Filter minimum transactions
    bt_min = bt[bt["num_transactions"] >= min_transactions].copy()

    if len(bt_min) > 0:
        _range = lambda s: s.max() - s.min() + 0.01
        bt_min["cart_score"] = (bt_min["avg_cart_value"] - bt_min["avg_cart_value"].min()) / _range(bt_min["avg_cart_value"]) * 30
        bt_min["units_score"] = (bt_min["avg_units_per_cart"] - bt_min["avg_units_per_cart"].min()) / _range(bt_min["avg_units_per_cart"]) * 25
        bt_min["discount_score"] = (100 - bt_min["pct_sales_discounted"]) / 100 * 20
        loy_max = bt_min["loyalty_enrollments"].max()
        bt_min["loyalty_score"] = (bt_min["loyalty_enrollments"] / loy_max * 15) if loy_max > 0 else 0
        bt_min["f2f_score"] = bt_min["face_to_face_pct"] / 100 * 10
        bt_min["sales_score"] = (
            bt_min["cart_score"] + bt_min["units_score"] + bt_min["discount_score"]
            + bt_min["loyalty_score"] + bt_min["f2f_score"]
        ).round(0)
    else:
        bt_min = bt.copy()
        bt_min["sales_score"] = 0

    bt_min["tier"] = bt_min["sales_score"].apply(_get_tier)
    return bt_min.sort_values("sales_score", ascending=False)


def _get_tier(score: float) -> str:
    if score >= 70:
        return "Top Performer"
    if score >= 50:
        return "Solid"
    if score >= 30:
        return "Developing"
    return "Needs Coaching"


def budtender_summary(bt_scored: pd.DataFrame) -> dict:
    """Summary KPIs for the budtender report."""
    return {
        "total_budtenders": int(len(bt_scored)),
        "avg_sales_score": round(float(bt_scored["sales_score"].mean()), 1),
        "top_performers": int((bt_scored["tier"] == "Top Performer").sum()),
        "needs_coaching": int((bt_scored["tier"] == "Needs Coaching").sum()),
    }
