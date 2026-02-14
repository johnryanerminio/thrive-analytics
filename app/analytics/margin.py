"""
Margin analytics — full price vs discounted, margin by group, category benchmarks.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics.common import safe_divide, calc_margin, fillna_numeric


def company_margin_totals(regular_df: pd.DataFrame) -> dict:
    """Company-wide margin KPIs.

    Uses a single groupby on has_discount instead of two full-DataFrame filters.
    """
    if regular_df.empty:
        return {k: 0 for k in ["total_units", "total_revenue", "total_cost", "net_profit",
                                "full_price_units", "full_price_sales", "full_price_cost",
                                "discounted_units", "discounted_sales", "discounted_cost",
                                "pct_full_price", "pct_discounted",
                                "full_price_margin", "discounted_margin", "blended_margin"]}

    g = regular_df.groupby("has_discount").agg(
        quantity=("quantity", "sum"),
        revenue=("actual_revenue", "sum"),
        cost=("cost", "sum"),
        profit=("net_profit", "sum"),
    )

    zeros = pd.Series({"quantity": 0, "revenue": 0.0, "cost": 0.0, "profit": 0.0})
    fp = g.loc[False] if False in g.index else zeros
    disc = g.loc[True] if True in g.index else zeros

    total_revenue = fp["revenue"] + disc["revenue"]
    total_cost = fp["cost"] + disc["cost"]

    return {
        "total_units": int(fp["quantity"] + disc["quantity"]),
        "total_revenue": float(total_revenue),
        "total_cost": float(total_cost),
        "net_profit": float(fp["profit"] + disc["profit"]),
        "full_price_units": int(fp["quantity"]),
        "full_price_sales": float(fp["revenue"]),
        "full_price_cost": float(fp["cost"]),
        "discounted_units": int(disc["quantity"]),
        "discounted_sales": float(disc["revenue"]),
        "discounted_cost": float(disc["cost"]),
        "pct_full_price": round(safe_divide(fp["revenue"], total_revenue) * 100, 1),
        "pct_discounted": round(safe_divide(disc["revenue"], total_revenue) * 100, 1),
        "full_price_margin": round(calc_margin(fp["revenue"], fp["cost"]), 1),
        "discounted_margin": round(calc_margin(disc["revenue"], disc["cost"]), 1),
        "blended_margin": round(calc_margin(total_revenue, total_cost), 1),
    }


def margin_by_group(regular_df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Full-price vs discounted margin breakdown by group column.

    Uses a single groupby+unstack instead of 3 separate groupbys + 2 merges.
    """
    if regular_df.empty:
        return pd.DataFrame(columns=["name"])

    # Single groupby pass on [group_col, has_discount]
    g = regular_df.groupby([group_col, "has_discount"]).agg(
        units=("quantity", "sum"),
        revenue=("actual_revenue", "sum"),
        cost=("cost", "sum"),
        profit=("net_profit", "sum"),
    )
    u = g.unstack(level="has_discount", fill_value=0)

    levels = u.columns.get_level_values(1)
    has_fp = False in levels
    has_disc = True in levels

    result = pd.DataFrame(index=u.index)
    result["full_price_units"] = u[("units", False)] if has_fp else 0
    result["full_price_sales"] = u[("revenue", False)] if has_fp else 0.0
    result["full_price_cost"] = u[("cost", False)] if has_fp else 0.0
    result["discounted_units"] = u[("units", True)] if has_disc else 0
    result["discounted_sales"] = u[("revenue", True)] if has_disc else 0.0
    result["discounted_cost"] = u[("cost", True)] if has_disc else 0.0

    result["total_units"] = result["full_price_units"] + result["discounted_units"]
    result["total_revenue"] = result["full_price_sales"] + result["discounted_sales"]
    result["total_cost"] = result["full_price_cost"] + result["discounted_cost"]
    result["net_profit"] = u["profit"].sum(axis=1)

    rev_safe = result["total_revenue"].replace(0, np.nan)
    result["pct_full_price"] = (result["full_price_sales"] / rev_safe * 100).round(1)
    result["pct_discounted"] = (result["discounted_sales"] / rev_safe * 100).round(1)
    result["full_price_margin"] = ((result["full_price_sales"] - result["full_price_cost"]) / result["full_price_sales"].replace(0, np.nan) * 100).round(1)
    result["discounted_margin"] = ((result["discounted_sales"] - result["discounted_cost"]) / result["discounted_sales"].replace(0, np.nan) * 100).round(1)
    result["blended_margin"] = ((result["total_revenue"] - result["total_cost"]) / rev_safe * 100).round(1)

    return fillna_numeric(result).reset_index().rename(columns={group_col: "name"}).sort_values("total_revenue", ascending=False)


def brand_margin_summary(brand_df: pd.DataFrame) -> dict:
    """Margin summary for a single brand."""
    total_units = brand_df["quantity"].sum()
    total_revenue = brand_df["actual_revenue"].sum()
    total_cost = brand_df["cost"].sum()
    total_discounts = brand_df["discounts"].sum()
    total_profit = brand_df["net_profit"].sum()

    fp = brand_df[~brand_df["has_discount"]]
    disc = brand_df[brand_df["has_discount"]]

    fp_revenue = fp["actual_revenue"].sum()
    fp_cost = fp["cost"].sum()
    disc_revenue = disc["actual_revenue"].sum()
    disc_cost = disc["cost"].sum()

    return {
        "total_units": int(total_units),
        "total_revenue": float(total_revenue),
        "total_cost": float(total_cost),
        "total_discounts": float(total_discounts),
        "total_profit": float(total_profit),
        "overall_margin": round(calc_margin(total_revenue, total_cost), 1),
        "fp_margin": round(calc_margin(fp_revenue, fp_cost), 1),
        "disc_margin": round(calc_margin(disc_revenue, disc_cost), 1),
        "pct_full_price": round(safe_divide(fp_revenue, total_revenue) * 100, 1),
        "avg_discount_rate": round(safe_divide(total_discounts, total_revenue + total_discounts) * 100, 1),
        "fp_revenue": float(fp_revenue),
        "disc_revenue": float(disc_revenue),
    }


def brand_category_breakdown(
    brand_df: pd.DataFrame,
    category_margin_lookup: dict[str, float],
    brand_category_rankings: pd.DataFrame,
    brand_name: str,
) -> pd.DataFrame:
    """Per-category breakdown for a brand, including vs-category comparison."""
    cats = brand_df.groupby("category_clean").agg(
        units=("quantity", "sum"),
        revenue=("actual_revenue", "sum"),
        cost=("cost", "sum"),
        profit=("net_profit", "sum"),
        discounts=("discounts", "sum"),
    ).reset_index()

    cats["margin"] = ((cats["revenue"] - cats["cost"]) / cats["revenue"].replace(0, np.nan) * 100).round(1)
    cats["category_avg_margin"] = cats["category_clean"].map(category_margin_lookup)
    cats["vs_category"] = (cats["margin"] - cats["category_avg_margin"]).round(1)

    for idx, row in cats.iterrows():
        cat = row["category_clean"]
        rank_data = brand_category_rankings[
            (brand_category_rankings["category_clean"] == cat) &
            (brand_category_rankings["brand_clean"] == brand_name)
        ]
        if len(rank_data) > 0:
            cats.loc[idx, "rank"] = int(rank_data["rank"].values[0])
            cats.loc[idx, "total_brands"] = int(rank_data["total_brands"].values[0])
        else:
            cats.loc[idx, "rank"] = 0
            cats.loc[idx, "total_brands"] = 0

    return cats.sort_values("revenue", ascending=False)


def discount_depth_distribution(brand_df: pd.DataFrame) -> list[dict]:
    """Discount depth tier distribution: 0%, 1-10%, 11-20%, 21-30%, 31%+."""
    df = brand_df.copy()
    pre = df["pre_discount_revenue"] if "pre_discount_revenue" in df.columns else df["actual_revenue"] + df["discounts"]
    df["discount_pct"] = (df["discounts"] / pre.replace(0, np.nan) * 100).fillna(0)

    tiers = [
        ("0% (Full Price)", 0, 0),
        ("1-10%", 0.01, 10),
        ("11-20%", 10.01, 20),
        ("21-30%", 20.01, 30),
        ("31%+", 30.01, 100),
    ]

    result = []
    total = len(df)
    for label, lo, hi in tiers:
        if lo == 0 and hi == 0:
            count = (df["discount_pct"] == 0).sum()
        else:
            count = ((df["discount_pct"] > lo) & (df["discount_pct"] <= hi)).sum()
        revenue = df.loc[
            (df["discount_pct"] >= lo) & (df["discount_pct"] <= hi), "actual_revenue"
        ].sum() if lo == 0 and hi == 0 else df.loc[
            (df["discount_pct"] > lo) & (df["discount_pct"] <= hi), "actual_revenue"
        ].sum()
        result.append({
            "tier": label,
            "transactions": int(count),
            "pct_of_transactions": round(safe_divide(count, total) * 100, 1),
            "revenue": float(revenue),
            "avg_discount": round(df.loc[
                (df["discount_pct"] >= (lo if lo == 0 else lo)) &
                (df["discount_pct"] <= hi), "discount_pct"
            ].mean(), 1) if count > 0 else 0,
        })

    return result
