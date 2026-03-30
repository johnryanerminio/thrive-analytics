"""
Margin waterfall decomposition — breaks margin change into mix, price, cost,
and discount effects between current and prior period.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from app.analytics.common import safe_divide, sanitize_for_json
from app.data.store import DataStore
from app.data.schemas import PeriodFilter, PeriodType


def _category_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-category stats needed for waterfall decomposition."""
    if df.empty:
        return pd.DataFrame(columns=[
            "category", "revenue", "cost", "quantity", "discounts",
            "pre_discount_revenue", "share", "margin", "revenue_per_unit",
            "cost_per_unit", "discount_rate",
        ])

    cats = df.groupby("category_clean", observed=True).agg(
        revenue=("actual_revenue", "sum"),
        cost=("cost", "sum"),
        quantity=("quantity", "sum"),
        discounts=("discounts", "sum"),
    ).reset_index().rename(columns={"category_clean": "category"})

    total_revenue = cats["revenue"].sum()
    cats["pre_discount_revenue"] = cats["revenue"] + cats["discounts"]
    cats["share"] = cats["revenue"] / total_revenue * 100 if total_revenue else 0.0
    rev_safe = cats["revenue"].replace(0, np.nan)
    qty_safe = cats["quantity"].replace(0, np.nan)
    cats["margin"] = ((cats["revenue"] - cats["cost"]) / rev_safe * 100).fillna(0.0)
    cats["revenue_per_unit"] = (cats["revenue"] / qty_safe).fillna(0.0)
    cats["cost_per_unit"] = (cats["cost"] / qty_safe).fillna(0.0)
    pre_safe = cats["pre_discount_revenue"].replace(0, np.nan)
    cats["discount_rate"] = (cats["discounts"] / pre_safe * 100).fillna(0.0)

    return cats


def _blended_margin(df: pd.DataFrame) -> float:
    """Compute blended margin % for a DataFrame."""
    if df.empty:
        return 0.0
    revenue = df["actual_revenue"].sum()
    cost = df["cost"].sum()
    return safe_divide(revenue - cost, revenue) * 100


def _blended_discount_rate(df: pd.DataFrame) -> float:
    """Compute blended discount rate % for a DataFrame."""
    if df.empty:
        return 0.0
    discounts = df["discounts"].sum()
    revenue = df["actual_revenue"].sum()
    pre_discount = revenue + discounts
    return safe_divide(discounts, pre_discount) * 100


def _default_prior_period(store: DataStore) -> tuple[pd.DataFrame, str]:
    """When no period is given, compare last 6 months vs prior 6 months."""
    regular = store.get_regular()
    if regular.empty:
        return pd.DataFrame(), "Prior 6 months"

    max_date = regular["sale_date"].max()
    if hasattr(max_date, "date"):
        max_date = max_date.date() if callable(max_date.date) else max_date
    if isinstance(max_date, pd.Timestamp):
        max_date = max_date.date()

    # Current = last 6 months ending at max_date
    # Prior = 6 months before that
    current_start = max_date - dt.timedelta(days=180)
    prior_end = current_start - dt.timedelta(days=1)
    prior_start = prior_end - dt.timedelta(days=180)

    prior_period = PeriodFilter(
        period_type=PeriodType.CUSTOM,
        start_date=prior_start,
        end_date=prior_end,
    )
    prior_df = store.get_regular(prior_period)
    label = f"{prior_start:%b %Y} to {prior_end:%b %Y}"
    return prior_df, label


def _empty_result() -> dict:
    """Return a null/empty waterfall result when data is insufficient."""
    return sanitize_for_json({
        "prior_margin": None,
        "current_margin": None,
        "total_change_pts": None,
        "effects": [],
        "residual_pts": None,
        "period_labels": {"current": "N/A", "prior": "N/A"},
        "category_detail": [],
    })


def margin_waterfall(
    regular_df: pd.DataFrame,
    store: DataStore,
    period: PeriodFilter | None,
) -> dict:
    """Decompose margin change between current and prior period into root causes.

    Parameters
    ----------
    regular_df : pd.DataFrame
        Already-filtered regular sales for the *current* period.
    store : DataStore
        Used to fetch prior-period data via ``store.get_regular(period.previous())``.
    period : PeriodFilter | None
        Current period filter.  If None, falls back to last-6-months vs prior-6-months.

    Returns
    -------
    dict with keys: prior_margin, current_margin, total_change_pts, effects,
    residual_pts, period_labels, category_detail.
    """
    # --- Current period ---------------------------------------------------
    if regular_df.empty:
        return _empty_result()

    current_margin = _blended_margin(regular_df)
    current_discount_rate = _blended_discount_rate(regular_df)
    current_label = period.label if period else "Current 6 months"

    # --- Prior period -----------------------------------------------------
    if period is not None:
        prior_period = period.previous()
        prior_df = store.get_regular(prior_period)
        prior_label = prior_period.label
    else:
        prior_df, prior_label = _default_prior_period(store)

    if prior_df.empty:
        return _empty_result()

    prior_margin = _blended_margin(prior_df)
    prior_discount_rate = _blended_discount_rate(prior_df)
    total_change = current_margin - prior_margin

    # --- Per-category stats -----------------------------------------------
    cur_cats = _category_stats(regular_df)
    pri_cats = _category_stats(prior_df)

    # Align on union of categories
    all_categories = sorted(
        set(cur_cats["category"].tolist()) | set(pri_cats["category"].tolist())
    )

    cur_idx = cur_cats.set_index("category")
    pri_idx = pri_cats.set_index("category")

    # --- Decompose effects ------------------------------------------------
    mix_effect = 0.0
    price_effect = 0.0
    cost_effect = 0.0
    category_detail = []

    for cat in all_categories:
        cur_share = cur_idx.loc[cat, "share"] / 100 if cat in cur_idx.index else 0.0
        pri_share = pri_idx.loc[cat, "share"] / 100 if cat in pri_idx.index else 0.0
        cur_margin = cur_idx.loc[cat, "margin"] if cat in cur_idx.index else 0.0
        pri_margin = pri_idx.loc[cat, "margin"] if cat in pri_idx.index else 0.0
        cur_rpu = cur_idx.loc[cat, "revenue_per_unit"] if cat in cur_idx.index else 0.0
        pri_rpu = pri_idx.loc[cat, "revenue_per_unit"] if cat in pri_idx.index else 0.0
        cur_cpu = cur_idx.loc[cat, "cost_per_unit"] if cat in cur_idx.index else 0.0
        pri_cpu = pri_idx.loc[cat, "cost_per_unit"] if cat in pri_idx.index else 0.0

        # Mix effect: shift in category weight × prior category margin
        cat_mix = (cur_share - pri_share) * pri_margin
        mix_effect += cat_mix

        # Price effect: within-category price change impact on margin
        if cur_rpu != 0:
            cat_price = cur_share * (cur_rpu - pri_rpu) / cur_rpu * cur_margin
        else:
            cat_price = 0.0
        price_effect += cat_price

        # Cost effect: within-category cost change impact (lower cost = positive)
        if cur_rpu != 0:
            cat_cost = cur_share * (pri_cpu - cur_cpu) / cur_rpu * 100
        else:
            cat_cost = 0.0
        cost_effect += cat_cost

        # Category detail for drill-down
        contribution = cur_share * cur_margin - pri_share * pri_margin
        category_detail.append({
            "category": cat,
            "prior_share": round(pri_share * 100, 2),
            "current_share": round(cur_share * 100, 2),
            "prior_margin": round(float(pri_margin), 2),
            "current_margin": round(float(cur_margin), 2),
            "contribution_pts": round(float(contribution), 2),
        })

    # Discount effect: change in discount rate (more discounts = negative)
    discount_effect = (current_discount_rate - prior_discount_rate) * -1

    # --- Build effects list -----------------------------------------------
    effects = [
        {
            "name": "Mix Effect",
            "impact_pts": round(float(mix_effect), 2),
            "direction": "positive" if mix_effect > 0 else "negative" if mix_effect < 0 else "neutral",
        },
        {
            "name": "Price Effect",
            "impact_pts": round(float(price_effect), 2),
            "direction": "positive" if price_effect > 0 else "negative" if price_effect < 0 else "neutral",
        },
        {
            "name": "Cost Effect",
            "impact_pts": round(float(cost_effect), 2),
            "direction": "positive" if cost_effect > 0 else "negative" if cost_effect < 0 else "neutral",
        },
        {
            "name": "Discount Effect",
            "impact_pts": round(float(discount_effect), 2),
            "direction": "positive" if discount_effect > 0 else "negative" if discount_effect < 0 else "neutral",
        },
    ]

    sum_effects = mix_effect + price_effect + cost_effect + discount_effect
    residual = total_change - sum_effects

    # Sort category detail by absolute contribution descending
    category_detail.sort(key=lambda x: abs(x["contribution_pts"]), reverse=True)

    result = {
        "prior_margin": round(float(prior_margin), 2),
        "current_margin": round(float(current_margin), 2),
        "total_change_pts": round(float(total_change), 2),
        "effects": effects,
        "residual_pts": round(float(residual), 2),
        "period_labels": {"current": current_label, "prior": prior_label},
        "category_detail": category_detail,
    }

    return sanitize_for_json(result)
