"""
Basket analytics — basket size trends, product co-purchase pairs,
category co-purchase matrix, and basket KPIs.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from itertools import combinations

from app.analytics.common import safe_divide, sanitize_for_json

# Performance guard: sample receipts down when the input exceeds this many rows.
_MAX_ROWS_FOR_COPURCHASE = 500_000


def basket_analysis(regular_df: pd.DataFrame) -> dict:
    """Return basket-level analytics from regular transaction data.

    Parameters
    ----------
    regular_df : DataFrame
        Must contain columns: receipt_id, actual_revenue, quantity, product,
        category_clean, brand_clean, year, month, customer_id.

    Returns
    -------
    dict with keys: kpis, monthly_trend, product_pairs, category_pairs
    """
    if regular_df is None or regular_df.empty:
        return sanitize_for_json(_empty_result())

    df = regular_df.copy()

    # --- Basket-level aggregation (used by several sections) ----------------
    basket_agg = (
        df.groupby("receipt_id", observed=True)
        .agg(
            revenue=("actual_revenue", "sum"),
            items=("quantity", "sum"),
            n_products=("product", "nunique"),
            year=("year", "first"),
            month=("month", "first"),
        )
    )
    total_baskets = len(basket_agg)

    # --- 1. Monthly basket metrics trend ------------------------------------
    monthly_trend = _monthly_trend(basket_agg)

    # --- 2. Product co-purchase pairs (top 20) ------------------------------
    product_pairs = _product_copurchase(df, total_baskets)

    # --- 3. Category co-purchase matrix -------------------------------------
    category_pairs = _category_copurchase(df, total_baskets)

    # --- 4. KPIs ------------------------------------------------------------
    kpis = _compute_kpis(basket_agg, monthly_trend, total_baskets)

    return sanitize_for_json({
        "kpis": kpis,
        "monthly_trend": monthly_trend,
        "product_pairs": product_pairs,
        "category_pairs": category_pairs,
    })


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _empty_result() -> dict:
    return {
        "kpis": {
            "avg_basket_value": 0,
            "avg_items_per_basket": 0,
            "basket_trend": "stable",
            "multi_item_basket_pct": 0,
            "total_baskets": 0,
        },
        "monthly_trend": [],
        "product_pairs": [],
        "category_pairs": [],
    }


def _monthly_trend(basket_agg: pd.DataFrame) -> list[dict]:
    """Avg basket value & items per basket by year/month."""
    monthly = (
        basket_agg.groupby(["year", "month"], observed=True)
        .agg(
            avg_basket=("revenue", "mean"),
            avg_items=("items", "mean"),
            transactions=("revenue", "size"),
        )
        .reset_index()
        .sort_values(["year", "month"])
    )
    monthly["avg_basket"] = monthly["avg_basket"].round(2)
    monthly["avg_items"] = monthly["avg_items"].round(2)

    return [
        {
            "year": int(r.year),
            "month": int(r.month),
            "label": f"{int(r.year)}-{int(r.month):02d}",
            "avg_basket": r.avg_basket,
            "avg_items": r.avg_items,
            "transactions": int(r.transactions),
        }
        for r in monthly.itertuples(index=False)
    ]


def _product_copurchase(df: pd.DataFrame, total_baskets: int) -> list[dict]:
    """Top 20 product pairs purchased together in the same basket."""
    # Sample if needed for performance
    sampled = _sample_if_needed(df)

    # Get distinct products per receipt
    receipt_products = (
        sampled.groupby("receipt_id", observed=True)["product"]
        .apply(lambda x: frozenset(x.unique()))
    )
    # Keep only multi-product baskets
    multi = receipt_products[receipt_products.apply(len) >= 2]
    n_multi = len(multi)

    if n_multi == 0:
        return []

    # Count pairs
    pair_counts: dict[tuple[str, str], int] = {}
    for products in multi:
        # Limit combinations per basket to avoid explosion on very large baskets
        prods = sorted(products)
        if len(prods) > 20:
            prods = prods[:20]
        for a, b in combinations(prods, 2):
            key = (a, b)
            pair_counts[key] = pair_counts.get(key, 0) + 1

    # Top 20
    top_pairs = sorted(pair_counts.items(), key=lambda x: x[1], reverse=True)[:20]

    return [
        {
            "product_a": a,
            "product_b": b,
            "co_purchase_count": count,
            "pct_of_multi_baskets": round(safe_divide(count, n_multi) * 100, 2),
        }
        for (a, b), count in top_pairs
    ]


def _category_copurchase(df: pd.DataFrame, total_baskets: int) -> list[dict]:
    """Category co-purchase matrix: pairs of categories bought in same basket."""
    sampled = _sample_if_needed(df)

    # Distinct categories per receipt
    receipt_cats = (
        sampled.groupby("receipt_id", observed=True)["category_clean"]
        .apply(lambda x: frozenset(x.unique()))
    )

    # Count baskets per category (for rate calculation)
    cat_basket_counts: dict[str, int] = {}
    for cats in receipt_cats:
        for c in cats:
            cat_basket_counts[c] = cat_basket_counts.get(c, 0) + 1

    # Only consider categories with 1000+ baskets
    qualifying_cats = {c for c, n in cat_basket_counts.items() if n >= 1000}

    # Multi-category baskets only
    multi = receipt_cats[receipt_cats.apply(len) >= 2]
    if len(multi) == 0:
        return []

    pair_counts: dict[tuple[str, str], int] = {}
    for cats in multi:
        qualified = sorted(c for c in cats if c in qualifying_cats)
        for a, b in combinations(qualified, 2):
            pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1

    results = []
    for (a, b), count in sorted(pair_counts.items(), key=lambda x: x[1], reverse=True):
        # Rate relative to category_a baskets
        rate_a = round(safe_divide(count, cat_basket_counts.get(a, 0)) * 100, 2)
        results.append({
            "category_a": a,
            "category_b": b,
            "co_purchase_count": count,
            "co_purchase_rate": rate_a,
        })

    return results


def _compute_kpis(
    basket_agg: pd.DataFrame,
    monthly_trend: list[dict],
    total_baskets: int,
) -> dict:
    """Overall basket KPIs."""
    avg_basket_value = round(float(basket_agg["revenue"].mean()), 2) if total_baskets else 0
    avg_items = round(float(basket_agg["items"].mean()), 2) if total_baskets else 0
    multi_item_pct = round(
        safe_divide((basket_agg["n_products"] >= 2).sum(), total_baskets) * 100, 2
    )

    # Trend: compare last 3 months vs prior 3 months
    basket_trend = "stable"
    if len(monthly_trend) >= 6:
        recent_3 = np.mean([m["avg_basket"] for m in monthly_trend[-3:]])
        prior_3 = np.mean([m["avg_basket"] for m in monthly_trend[-6:-3]])
        if prior_3 > 0:
            change_pct = (recent_3 - prior_3) / prior_3 * 100
            if change_pct > 5:
                basket_trend = "growing"
            elif change_pct < -5:
                basket_trend = "shrinking"

    return {
        "avg_basket_value": avg_basket_value,
        "avg_items_per_basket": avg_items,
        "basket_trend": basket_trend,
        "multi_item_basket_pct": multi_item_pct,
        "total_baskets": total_baskets,
    }


def _sample_if_needed(df: pd.DataFrame) -> pd.DataFrame:
    """Downsample by receipt_id if the DataFrame exceeds the row threshold."""
    if len(df) <= _MAX_ROWS_FOR_COPURCHASE:
        return df

    # Sample a subset of receipt IDs proportionally
    receipt_ids = df["receipt_id"].unique()
    target_receipts = int(len(receipt_ids) * (_MAX_ROWS_FOR_COPURCHASE / len(df)))
    target_receipts = max(target_receipts, 1000)  # floor
    rng = np.random.RandomState(42)
    sampled_ids = rng.choice(receipt_ids, size=min(target_receipts, len(receipt_ids)), replace=False)
    return df[df["receipt_id"].isin(set(sampled_ids))]
