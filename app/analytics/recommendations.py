"""
Recommendation engines — dispensary-facing and brand-facing.
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from app.analytics.common import safe_divide, calc_margin


# ---------------------------------------------------------------------------
# Dispensary-side brand recommendations
# ---------------------------------------------------------------------------

def dispensary_recommendations(
    brand_name: str,
    brand_summary: dict,
    category_breakdown: pd.DataFrame,
    primary_category: str,
    primary_cat_margin: float,
) -> list[dict]:
    """Generate actionable recommendations for the dispensary about a brand."""
    recs = []
    margin = brand_summary["overall_margin"]
    margin_vs_cat = margin - primary_cat_margin
    pct_fp = brand_summary["pct_full_price"]
    disc_margin = brand_summary["disc_margin"]
    total_revenue = brand_summary["total_revenue"]

    # Per-category below-average warnings
    for _, row in category_breakdown.iterrows():
        vs = row.get("vs_category", 0)
        if pd.notna(vs) and vs < -10:
            cat = row["category_clean"]
            cat_margin = row.get("margin", 0)
            rank = int(row.get("rank", 0))
            total = int(row.get("total_brands", 0))
            recs.append({
                "severity": "red",
                "title": f"{cat}: BELOW CATEGORY AVERAGE",
                "detail": f"Margin ({cat_margin:.1f}%) is {abs(vs):.0f} pts below {cat} average. "
                          f"Ranked #{rank} of {total}. Strong case for cost negotiation.",
                "action": f"Request {abs(vs)/2:.0f}% cost reduction or evaluate alternative {cat} brands.",
            })

    # Overall benchmark gap
    if margin_vs_cat < -5:
        recs.append({
            "severity": "yellow",
            "title": "CATEGORY BENCHMARK GAP",
            "detail": f"Overall margin ({margin:.1f}%) trails {primary_category} average "
                      f"({primary_cat_margin:.1f}%) by {abs(margin_vs_cat):.1f} pts.",
            "action": "Negotiate cost reduction or increase retail price.",
        })

    # Promotion dependency
    if pct_fp < 25:
        recs.append({
            "severity": "red",
            "title": "HIGH PROMOTION DEPENDENCY",
            "detail": f"Only {pct_fp:.0f}% sells at full price. Heavy discounting required.",
            "action": "Test reducing deal frequency — track velocity without promos.",
        })

    # Low discounted margin
    if disc_margin < 35 and brand_summary["disc_revenue"] > 0:
        recs.append({
            "severity": "red",
            "title": "LOW DISCOUNTED MARGIN",
            "detail": f"Margin drops to {disc_margin:.1f}% when discounted.",
            "action": "Cap discount depth at 20% or negotiate lower wholesale cost.",
        })

    # Strong performer
    if margin_vs_cat >= 5:
        rank = int(category_breakdown.iloc[0].get("rank", 0)) if len(category_breakdown) > 0 else 0
        if rank > 0 and rank <= 5:
            recs.append({
                "severity": "green",
                "title": "STRONG PERFORMER",
                "detail": f"Ranked #{rank} in {primary_category} with {margin_vs_cat:.1f} pts above average.",
                "action": "Expand shelf space and prioritize this brand in category.",
            })

    # Volume leverage
    if total_revenue > 5000:
        recs.append({
            "severity": "info",
            "title": "VOLUME LEVERAGE",
            "detail": f"${total_revenue:,.0f} revenue provides negotiating leverage.",
            "action": "Use volume as leverage in next vendor meeting.",
        })

    return recs


# ---------------------------------------------------------------------------
# Brand-facing recommendations
# ---------------------------------------------------------------------------

def brand_facing_recommendations(
    brand_name: str,
    brand_df: pd.DataFrame,
    all_regular_df: pd.DataFrame,
    store_coverage: dict,
    velocity_data: list[dict],
) -> list[dict]:
    """Generate growth opportunity recommendations for a brand."""
    recs = []

    # Store distribution gaps
    all_stores = all_regular_df["store_clean"].unique()
    brand_stores = brand_df["store_clean"].unique()
    missing = set(all_stores) - set(brand_stores)
    if missing:
        for store in sorted(missing):
            # Check category demand at the missing store
            store_cats = all_regular_df[all_regular_df["store_clean"] == store]["category_clean"].unique()
            brand_cats = brand_df["category_clean"].unique()
            overlap = set(store_cats) & set(brand_cats)
            if overlap:
                cat_rev = all_regular_df[
                    (all_regular_df["store_clean"] == store) &
                    (all_regular_df["category_clean"].isin(overlap))
                ]["actual_revenue"].sum()
                recs.append({
                    "type": "distribution",
                    "title": f"Expand to {store}",
                    "detail": f"Store has ${cat_rev:,.0f} in {', '.join(sorted(overlap))} — categories where {brand_name} competes.",
                    "priority": "high" if cat_rev > 10000 else "medium",
                })

    # SKU expansion opportunities (products at some stores but not all)
    brand_store_products = brand_df.groupby(["store_clean", "product"]).size().reset_index(name="count")
    product_store_count = brand_store_products.groupby("product")["store_clean"].nunique().reset_index()
    product_store_count.columns = ["product", "store_count"]
    partial = product_store_count[
        (product_store_count["store_count"] < len(brand_stores)) &
        (product_store_count["store_count"] >= 2)
    ]

    for _, row in partial.head(5).iterrows():
        present = set(brand_store_products[brand_store_products["product"] == row["product"]]["store_clean"])
        absent = set(brand_stores) - present
        if absent:
            recs.append({
                "type": "sku_expansion",
                "title": f"Add '{row['product']}' to {len(absent)} more store(s)",
                "detail": f"Carried in {row['store_count']} stores. Missing from: {', '.join(sorted(absent))}",
                "priority": "medium",
            })

    # Velocity improvement
    for v in velocity_data:
        if v.get("velocity_index", 100) < 80:
            recs.append({
                "type": "velocity",
                "title": f"Improve velocity in {v['category']}",
                "detail": f"Velocity index {v['velocity_index']:.0f} (below category average). "
                          f"{v['brand_units_per_day']:.1f} units/day vs {v['category_avg_units_per_day']:.1f} avg.",
                "priority": "medium",
            })

    return recs
