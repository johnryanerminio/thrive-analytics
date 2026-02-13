"""
Dashboard analytics — compute functions for company-wide dashboard pages.

Executive Summary, Month-over-Month, Store Performance, Year-End Summary.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import pandas as pd

from app.data.store import DataStore
from app.data.schemas import PeriodFilter
from app.analytics.common import safe_divide, pct_of_total, pct_change, sanitize_for_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _month_label(year: int, month: int) -> str:
    return f"{_MONTH_NAMES[month]} {year}"


def _ym_key(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def _monthly_groups(df: pd.DataFrame) -> list[dict]:
    """Group a DataFrame by year/month and compute per-month metrics."""
    if df.empty:
        return []

    grouped = df.groupby(["year", "month"]).agg(
        revenue=("actual_revenue", "sum"),
        profit=("net_profit", "sum"),
        cost=("cost", "sum"),
        units=("quantity", "sum"),
        transactions=("receipt_id", "nunique"),
        customers=("customer_id", "nunique"),
        discounts=("discounts", "sum"),
        pre_discount=("pre_discount_revenue", "sum"),
    ).reset_index().sort_values(["year", "month"])

    rows = []
    for _, r in grouped.iterrows():
        y, m = int(r["year"]), int(r["month"])
        rev = float(r["revenue"])
        profit = float(r["profit"])
        units = int(r["units"])
        disc = float(r["discounts"])
        pre_disc = float(r["pre_discount"])
        fp_rev = pre_disc - disc if pre_disc > 0 else rev  # approximation
        rows.append({
            "month": _ym_key(y, m),
            "label": _month_label(y, m),
            "year": y,
            "month_num": m,
            "revenue": rev,
            "profit": profit,
            "margin": safe_divide(profit, rev) * 100,
            "units": units,
            "transactions": int(r["transactions"]),
            "customers": int(r["customers"]),
            "full_price_pct": safe_divide(rev - disc, rev) * 100 if rev > 0 else 0.0,
        })
    return rows


def _sales_mix(regular: pd.DataFrame) -> dict:
    """Compute full-price vs discounted sales mix."""
    if regular.empty:
        return {
            "full_price_pct": 0.0, "discounted_pct": 0.0,
            "health": "concern",
            "full_price_revenue": 0.0, "discounted_revenue": 0.0,
            "full_price_margin": 0.0, "discounted_margin": 0.0,
            "margin_gap_pts": 0.0,
        }

    fp = regular[regular["deal_type"] == "NO DEAL"]
    disc = regular[regular["deal_type"] != "NO DEAL"]

    fp_rev = float(fp["actual_revenue"].sum())
    fp_profit = float(fp["net_profit"].sum())
    disc_rev = float(disc["actual_revenue"].sum())
    disc_profit = float(disc["net_profit"].sum())
    total_rev = fp_rev + disc_rev

    fp_pct = pct_of_total(fp_rev, total_rev)
    fp_margin = safe_divide(fp_profit, fp_rev) * 100
    disc_margin = safe_divide(disc_profit, disc_rev) * 100

    if fp_pct >= 35:
        health = "healthy"
    elif fp_pct >= 25:
        health = "watch"
    else:
        health = "concern"

    return {
        "full_price_pct": round(fp_pct, 1),
        "discounted_pct": round(100 - fp_pct, 1),
        "health": health,
        "full_price_revenue": fp_rev,
        "discounted_revenue": disc_rev,
        "full_price_margin": round(fp_margin, 1),
        "discounted_margin": round(disc_margin, 1),
        "margin_gap_pts": round(fp_margin - disc_margin, 1),
    }


def _excluded_transactions(store: DataStore, period: PeriodFilter | None) -> dict:
    """Count and categorize non-REGULAR transactions."""
    all_sales = store.get_sales(period)
    if all_sales.empty:
        return {"total": 0, "breakdown": []}

    excluded = all_sales[all_sales["transaction_type"] != "REGULAR"]
    if excluded.empty:
        return {"total": 0, "breakdown": []}

    by_type = excluded.groupby("transaction_type").agg(
        count=("receipt_id", "count"),
        value=("actual_revenue", "sum"),
        units=("quantity", "sum"),
    ).reset_index()

    breakdown = []
    for _, r in by_type.iterrows():
        breakdown.append({
            "type": str(r["transaction_type"]),
            "count": int(r["count"]),
            "value": float(r["value"]),
            "units": int(r["units"]),
        })

    return {
        "total": int(excluded.shape[0]),
        "total_value": float(excluded["actual_revenue"].sum()),
        "total_units": int(excluded["quantity"].sum()),
        "breakdown": sorted(breakdown, key=lambda x: x["value"], reverse=True),
    }


def _generate_insights(
    kpis: dict,
    monthly: list[dict],
    stores: list[dict],
    sales_mix: dict,
) -> list[dict]:
    """Auto-generate executive insights from the data."""
    insights = []
    margin = kpis.get("blended_margin", 0)
    fp_pct = sales_mix.get("full_price_pct", 0)

    # Margin health
    if margin >= 55:
        insights.append({
            "type": "success",
            "title": "Strong Margins",
            "detail": f"Blended margin of {margin:.1f}% is excellent — well above industry norms.",
        })
    elif margin < 40:
        insights.append({
            "type": "warning",
            "title": "Margin Pressure",
            "detail": f"Blended margin of {margin:.1f}% is below target. Review pricing and discount strategies.",
        })

    # Discount dependency
    if fp_pct < 30:
        insights.append({
            "type": "warning",
            "title": "High Discount Dependency",
            "detail": f"Only {fp_pct:.1f}% of revenue is full-price. {sales_mix.get('discounted_pct', 0):.1f}% of sales are discounted.",
        })
    elif fp_pct >= 40:
        insights.append({
            "type": "success",
            "title": "Healthy Sales Mix",
            "detail": f"{fp_pct:.1f}% of revenue is at full price, limiting margin erosion from discounts.",
        })

    # Margin gap
    gap = sales_mix.get("margin_gap_pts", 0)
    if gap > 15:
        insights.append({
            "type": "info",
            "title": "Significant Margin Gap",
            "detail": f"Full-price margin is {gap:.1f} pts higher than discounted. Discounts are cutting deep into profit.",
        })

    # Store-level warnings
    for s in stores:
        if s.get("margin", 100) < 40:
            insights.append({
                "type": "warning",
                "title": f"{s['name']} Needs Attention",
                "detail": f"Margin of {s['margin']:.1f}% is below 40%. Review store operations and pricing.",
            })

    # Month-over-month trend
    if len(monthly) >= 2:
        last = monthly[-1]
        prev = monthly[-2]
        rev_change = pct_change(last["revenue"], prev["revenue"])
        if rev_change is not None and rev_change < -10:
            insights.append({
                "type": "warning",
                "title": "Revenue Declining",
                "detail": f"{last['label']} revenue dropped {abs(rev_change):.1f}% vs {prev['label']}.",
            })
        margin_change = last["margin"] - prev["margin"]
        if margin_change > 3:
            insights.append({
                "type": "success",
                "title": "Margin Improving",
                "detail": f"Margin increased {margin_change:.1f} pts from {prev['label']} to {last['label']}.",
            })

    return insights[:6]  # Cap at 6 insights


# ---------------------------------------------------------------------------
# Executive Summary
# ---------------------------------------------------------------------------

def executive_summary(store: DataStore, period: PeriodFilter | None) -> dict:
    """Full executive summary with KPIs, trends, insights, and sales mix."""
    regular = store.get_regular(period)
    label = period.label if period else "All Time"

    if regular.empty:
        return sanitize_for_json({"period_label": label, "empty": True})

    # Core KPIs
    revenue = float(regular["actual_revenue"].sum())
    profit = float(regular["net_profit"].sum())
    units = int(regular["quantity"].sum())
    transactions = int(regular["receipt_id"].nunique())
    customers = int(regular["customer_id"].nunique())
    discounts = float(regular["discounts"].sum())
    margin = safe_divide(profit, revenue) * 100

    # Monthly trend
    monthly = _monthly_groups(regular)
    n_months = len(monthly) if monthly else 1

    # Best / worst months
    best_month = max(monthly, key=lambda m: m["revenue"]) if monthly else None
    worst_month = min(monthly, key=lambda m: m["revenue"]) if monthly else None

    kpis = {
        "total_revenue": revenue,
        "net_profit": profit,
        "blended_margin": round(margin, 1),
        "total_units": units,
        "total_transactions": transactions,
        "total_discounts": discounts,
        "full_price_pct": round(safe_divide(revenue - discounts, revenue) * 100, 1),
        "avg_basket": round(safe_divide(revenue, transactions), 2),
        "unique_customers": customers,
        "stores": len(store.stores()),
        "brands": len(store.brands()),
    }

    secondary = {
        "avg_monthly_revenue": round(revenue / n_months, 0),
        "avg_monthly_profit": round(profit / n_months, 0),
        "best_month": {"label": best_month["label"], "revenue": best_month["revenue"]} if best_month else None,
        "worst_month": {"label": worst_month["label"], "revenue": worst_month["revenue"]} if worst_month else None,
    }

    # Sales mix
    mix = _sales_mix(regular)

    # Top categories
    cat_agg = regular.groupby("category_clean").agg(
        revenue=("actual_revenue", "sum"),
        profit=("net_profit", "sum"),
    ).reset_index().sort_values("revenue", ascending=False).head(8)
    top_categories = []
    for _, r in cat_agg.iterrows():
        top_categories.append({
            "name": r["category_clean"],
            "revenue": float(r["revenue"]),
            "margin": round(safe_divide(float(r["profit"]), float(r["revenue"])) * 100, 1),
            "pct_of_total": round(pct_of_total(float(r["revenue"]), revenue), 1),
        })

    # Top stores
    store_agg = regular.groupby("store_clean").agg(
        revenue=("actual_revenue", "sum"),
        profit=("net_profit", "sum"),
        units=("quantity", "sum"),
    ).reset_index().sort_values("revenue", ascending=False)
    top_stores = []
    for _, r in store_agg.iterrows():
        top_stores.append({
            "name": r["store_clean"],
            "revenue": float(r["revenue"]),
            "margin": round(safe_divide(float(r["profit"]), float(r["revenue"])) * 100, 1),
            "units": int(r["units"]),
        })

    # Excluded transactions
    excluded = _excluded_transactions(store, period)

    # Auto-generated insights
    insights = _generate_insights(kpis, monthly, top_stores, mix)

    return sanitize_for_json({
        "period_label": label,
        "date_range": store.date_range(period),
        "kpis": kpis,
        "secondary_kpis": secondary,
        "monthly_trend": monthly,
        "excluded_transactions": excluded,
        "sales_mix": mix,
        "top_categories": top_categories,
        "top_stores": top_stores,
        "insights": insights,
    })


# ---------------------------------------------------------------------------
# Month-over-Month
# ---------------------------------------------------------------------------

def month_over_month(store: DataStore, period: PeriodFilter | None) -> dict:
    """Monthly breakdown with MoM percentage changes."""
    regular = store.get_regular(period)
    label = period.label if period else "All Time"

    if regular.empty:
        return sanitize_for_json({"period_label": label, "empty": True})

    monthly = _monthly_groups(regular)

    # Compute MoM changes
    for i, m in enumerate(monthly):
        if i == 0:
            m["mom_revenue_pct"] = None
            m["mom_profit_pct"] = None
            m["mom_margin_pts"] = None
            m["mom_units_pct"] = None
        else:
            prev = monthly[i - 1]
            m["mom_revenue_pct"] = pct_change(m["revenue"], prev["revenue"])
            m["mom_profit_pct"] = pct_change(m["profit"], prev["profit"])
            m["mom_margin_pts"] = round(m["margin"] - prev["margin"], 1)
            m["mom_units_pct"] = pct_change(m["units"], prev["units"])

    # Totals
    total_rev = sum(m["revenue"] for m in monthly)
    total_profit = sum(m["profit"] for m in monthly)
    total_units = sum(m["units"] for m in monthly)
    total_txns = sum(m["transactions"] for m in monthly)
    n = len(monthly)

    totals = {
        "revenue": total_rev,
        "profit": total_profit,
        "units": total_units,
        "transactions": total_txns,
        "avg_margin": round(safe_divide(total_profit, total_rev) * 100, 1),
        "avg_full_price_pct": round(sum(m["full_price_pct"] for m in monthly) / n, 1) if n else 0,
    }

    best = max(monthly, key=lambda m: m["revenue"]) if monthly else None
    worst = min(monthly, key=lambda m: m["revenue"]) if monthly else None

    return sanitize_for_json({
        "period_label": label,
        "months": monthly,
        "totals": totals,
        "best_month": {"label": best["label"], "revenue": best["revenue"]} if best else None,
        "worst_month": {"label": worst["label"], "revenue": worst["revenue"]} if worst else None,
    })


# ---------------------------------------------------------------------------
# Store Performance
# ---------------------------------------------------------------------------

def store_performance(store: DataStore, period: PeriodFilter | None) -> dict:
    """Store-level performance rankings."""
    regular = store.get_regular(period)
    label = period.label if period else "All Time"

    if regular.empty:
        return sanitize_for_json({"period_label": label, "empty": True})

    total_rev = float(regular["actual_revenue"].sum())

    store_agg = regular.groupby("store_clean").agg(
        revenue=("actual_revenue", "sum"),
        profit=("net_profit", "sum"),
        cost=("cost", "sum"),
        units=("quantity", "sum"),
        transactions=("receipt_id", "nunique"),
        customers=("customer_id", "nunique"),
        discounts=("discounts", "sum"),
    ).reset_index().sort_values("revenue", ascending=False)

    avg_margin = safe_divide(float(regular["net_profit"].sum()), total_rev) * 100

    stores_list = []
    for rank, (_, r) in enumerate(store_agg.iterrows(), 1):
        rev = float(r["revenue"])
        profit = float(r["profit"])
        margin = safe_divide(profit, rev) * 100
        disc = float(r["discounts"])
        fp_pct = safe_divide(rev - disc, rev) * 100

        # Margin status
        if margin >= avg_margin + 2:
            status = "green"
        elif margin <= avg_margin - 2:
            status = "red"
        else:
            status = "yellow"

        # Top brand and category for this store
        store_data = regular[regular["store_clean"] == r["store_clean"]]
        top_brand = store_data.groupby("brand_clean")["actual_revenue"].sum().idxmax() if not store_data.empty else ""
        top_cat = store_data.groupby("category_clean")["actual_revenue"].sum().idxmax() if not store_data.empty else ""

        stores_list.append({
            "name": r["store_clean"],
            "rank": rank,
            "revenue": rev,
            "share_pct": round(pct_of_total(rev, total_rev), 1),
            "profit": profit,
            "margin": round(margin, 1),
            "margin_status": status,
            "units": int(r["units"]),
            "transactions": int(r["transactions"]),
            "full_price_pct": round(fp_pct, 1),
            "unique_customers": int(r["customers"]),
            "top_brand": top_brand,
            "top_category": top_cat,
        })

    top_perf = stores_list[0]["name"] if stores_list else ""
    bottom_margins = sorted(stores_list, key=lambda s: s["margin"])
    bottom_perf = bottom_margins[0]["name"] if bottom_margins else ""

    return sanitize_for_json({
        "period_label": label,
        "date_range": store.date_range(period),
        "stores": stores_list,
        "company_avg_margin": round(avg_margin, 1),
        "top_performer": top_perf,
        "bottom_performer": bottom_perf,
    })


# ---------------------------------------------------------------------------
# Year-End Summary
# ---------------------------------------------------------------------------

def year_end_summary(store: DataStore, year: int) -> dict:
    """Annual summary report — printable, with highlights and YoY comparison."""
    from app.data.schemas import PeriodType

    period = PeriodFilter(PeriodType.YEAR, year=year)
    regular = store.get_regular(period)

    if regular.empty:
        return sanitize_for_json({"year": year, "empty": True})

    revenue = float(regular["actual_revenue"].sum())
    profit = float(regular["net_profit"].sum())
    units = int(regular["quantity"].sum())
    margin = safe_divide(profit, revenue) * 100
    discounts = float(regular["discounts"].sum())

    monthly = _monthly_groups(regular)
    n_months = len(monthly)

    # Header metadata
    n_stores = regular["store_clean"].nunique()
    n_brands = regular["brand_clean"].nunique()

    kpis = {
        "total_revenue": revenue,
        "total_profit": profit,
        "blended_margin": round(margin, 1),
        "total_units": units,
        "total_discounts": discounts,
        "full_price_pct": round(safe_divide(revenue - discounts, revenue) * 100, 1),
        "avg_monthly_revenue": round(revenue / max(n_months, 1), 0),
        "avg_monthly_profit": round(profit / max(n_months, 1), 0),
    }

    # Totals row for monthly summary
    totals = {
        "revenue": revenue,
        "profit": profit,
        "margin": round(margin, 1),
        "units": units,
        "full_price_pct": kpis["full_price_pct"],
    }

    # Highlights
    highlights = {}
    if monthly:
        best_rev = max(monthly, key=lambda m: m["revenue"])
        highlights["best_revenue"] = {"label": best_rev["label"], "value": best_rev["revenue"]}

        best_profit = max(monthly, key=lambda m: m["profit"])
        highlights["best_profit"] = {"label": best_profit["label"], "value": best_profit["profit"]}

        best_margin = max(monthly, key=lambda m: m["margin"])
        highlights["best_margin"] = {"label": best_margin["label"], "value": best_margin["margin"]}

        worst_profit = min(monthly, key=lambda m: m["profit"])
        highlights["worst_profit"] = {"label": worst_profit["label"], "value": worst_profit["profit"]}

    # Key insights
    key_insights = []
    if len(monthly) >= 2:
        first_margin = monthly[0]["margin"]
        last_margin = monthly[-1]["margin"]
        delta = last_margin - first_margin
        if delta > 1:
            key_insights.append({"type": "success", "title": "Margin Improved", "detail": f"{delta:.1f} pts change over the period"})
        elif delta < -1:
            key_insights.append({"type": "warning", "title": "Margin Declined", "detail": f"{abs(delta):.1f} pts decline over the period"})
        else:
            key_insights.append({"type": "info", "title": "Margin Stable", "detail": f"Less than 1 pt change over the period"})

    sales_mix = _sales_mix(regular)
    if sales_mix["full_price_pct"] < 30:
        key_insights.append({"type": "warning", "title": "Discount Dependency", "detail": f"{sales_mix['discounted_pct']:.1f}% of revenue from discounted sales"})
    else:
        key_insights.append({"type": "info", "title": "Discount Dependency Stable", "detail": f"{sales_mix['discounted_pct']:.1f}% of revenue from discounted sales"})

    mix_health = sales_mix["health"]
    health_labels = {"healthy": "Healthy Mix", "watch": "Monitor Closely", "concern": "Action Needed"}
    key_insights.append({
        "type": "success" if mix_health == "healthy" else ("warning" if mix_health == "concern" else "info"),
        "title": "Sales Mix " + health_labels.get(mix_health, ""),
        "detail": f"{sales_mix['full_price_pct']:.1f}% full price, {sales_mix['discounted_pct']:.1f}% discounted",
    })

    # YoY comparison
    yoy = None
    prev_period = PeriodFilter(PeriodType.YEAR, year=year - 1)
    prev_regular = store.get_regular(prev_period)
    if not prev_regular.empty:
        prev_rev = float(prev_regular["actual_revenue"].sum())
        prev_profit = float(prev_regular["net_profit"].sum())
        prev_units = int(prev_regular["quantity"].sum())
        yoy = {
            "prev_year": year - 1,
            "revenue_change_pct": pct_change(revenue, prev_rev),
            "profit_change_pct": pct_change(profit, prev_profit),
            "units_change_pct": pct_change(units, prev_units),
        }

    return sanitize_for_json({
        "year": year,
        "header": {
            "company": "Thrive Cannabis",
            "stores": n_stores,
            "brands": n_brands,
            "months": n_months,
        },
        "kpis": kpis,
        "monthly_summary": monthly,
        "totals": totals,
        "highlights": highlights,
        "key_insights": key_insights,
        "yoy_comparison": yoy,
    })
