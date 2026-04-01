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
from app.config import (
    SALES_MIX_HEALTHY_PCT, SALES_MIX_WATCH_PCT,
    MARGIN_EXCELLENT_PCT, MARGIN_BELOW_TARGET_PCT,
    DISCOUNT_DEPENDENCY_PCT, MARGIN_GAP_SIGNIFICANT_PTS,
    MONTHLY_OPEX, OPEX_CONFIGURED,
)


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

    grouped = df.groupby(["year", "month"], observed=True).agg(
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

    fp = regular[~regular["has_discount"]]
    disc = regular[regular["has_discount"]]

    fp_rev = float(fp["actual_revenue"].sum())
    fp_profit = float(fp["net_profit"].sum())
    disc_rev = float(disc["actual_revenue"].sum())
    disc_profit = float(disc["net_profit"].sum())
    total_rev = fp_rev + disc_rev

    fp_pct = pct_of_total(fp_rev, total_rev)
    fp_margin = safe_divide(fp_profit, fp_rev) * 100
    disc_margin = safe_divide(disc_profit, disc_rev) * 100

    if fp_pct >= SALES_MIX_HEALTHY_PCT:
        health = "healthy"
    elif fp_pct >= SALES_MIX_WATCH_PCT:
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

    by_type = excluded.groupby("transaction_type", observed=True).agg(
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
    if margin >= MARGIN_EXCELLENT_PCT:
        insights.append({
            "type": "success",
            "title": "Strong Margins",
            "detail": f"Blended margin of {margin:.1f}% is excellent — well above industry norms.",
        })
    elif margin < MARGIN_BELOW_TARGET_PCT:
        insights.append({
            "type": "warning",
            "title": "Margin Pressure",
            "detail": f"Blended margin of {margin:.1f}% is below target. Review pricing and discount strategies.",
        })

    # Discount dependency
    if fp_pct < DISCOUNT_DEPENDENCY_PCT:
        insights.append({
            "type": "warning",
            "title": "High Discount Dependency",
            "detail": f"Only {fp_pct:.1f}% of revenue is full-price. {sales_mix.get('discounted_pct', 0):.1f}% of sales are discounted.",
        })
    elif fp_pct >= SALES_MIX_HEALTHY_PCT + 5:
        insights.append({
            "type": "success",
            "title": "Healthy Sales Mix",
            "detail": f"{fp_pct:.1f}% of revenue is at full price, limiting margin erosion from discounts.",
        })

    # Margin gap
    gap = sales_mix.get("margin_gap_pts", 0)
    if gap > MARGIN_GAP_SIGNIFICANT_PTS:
        insights.append({
            "type": "info",
            "title": "Significant Margin Gap",
            "detail": f"Full-price margin is {gap:.1f} pts higher than discounted. Discounts are cutting deep into profit.",
        })

    # Store-level warnings
    for s in stores:
        if s.get("margin", 100) < MARGIN_BELOW_TARGET_PCT:
            insights.append({
                "type": "warning",
                "title": f"{s['name']} Needs Attention",
                "detail": f"Margin of {s['margin']:.1f}% is below {MARGIN_BELOW_TARGET_PCT}%. Review store operations and pricing.",
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
    cat_agg = regular.groupby("category_clean", observed=True).agg(
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
    store_agg = regular.groupby("store_clean", observed=True).agg(
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

    # P&L waterfall
    cost = float(regular["cost"].sum())
    gross_profit = revenue - cost
    gross_margin_pct = round(safe_divide(gross_profit, revenue) * 100, 1)
    pnl = {
        "revenue": revenue,
        "cogs": cost,
        "gross_profit": gross_profit,
        "gross_margin_pct": gross_margin_pct,
        "total_discounts": discounts,
        "net_after_discounts": revenue - discounts,
    }

    # EBITDA proxy (only if OpEx is configured)
    ebitda_proxy = None
    if OPEX_CONFIGURED:
        total_opex_labor = MONTHLY_OPEX["labor"] * n_months
        total_opex_rent = MONTHLY_OPEX["rent"] * n_months
        total_opex_utilities = MONTHLY_OPEX["utilities"] * n_months
        total_opex_other = MONTHLY_OPEX["other_opex"] * n_months
        total_opex = total_opex_labor + total_opex_rent + total_opex_utilities + total_opex_other
        total_da = MONTHLY_OPEX["depreciation"] * n_months
        ebit = gross_profit - total_opex
        ebitda = ebit + total_da
        ebitda_proxy = {
            "months": n_months,
            "gross_profit": gross_profit,
            "labor": total_opex_labor,
            "rent": total_opex_rent,
            "utilities": total_opex_utilities,
            "other_opex": total_opex_other,
            "total_opex": total_opex,
            "ebit": ebit,
            "depreciation": total_da,
            "ebitda": ebitda,
            "ebitda_margin_pct": round(safe_divide(ebitda, revenue) * 100, 1),
        }

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
        "pnl": pnl,
        "ebitda_proxy": ebitda_proxy,
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

    # Build lookup by (year, month_num) for YoY comparison
    by_ym = {(m["year"], m["month_num"]): m for m in monthly}

    # Compute MoM and YoY changes
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

        # YoY: compare to same month in previous year
        prev_year = by_ym.get((m["year"] - 1, m["month_num"]))
        if prev_year:
            m["yoy_revenue_pct"] = pct_change(m["revenue"], prev_year["revenue"])
            m["yoy_profit_pct"] = pct_change(m["profit"], prev_year["profit"])
            m["yoy_margin_pts"] = round(m["margin"] - prev_year["margin"], 1)
        else:
            m["yoy_revenue_pct"] = None
            m["yoy_profit_pct"] = None
            m["yoy_margin_pts"] = None

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

    # Multi-year comparison: show all available years side by side
    # Fetch any missing years from the full dataset
    from app.data.schemas import PeriodType
    years = sorted(set(m["year"] for m in monthly))
    latest_year = years[-1] if years else None

    # If we only have 1 year, try to fetch prior years
    if len(years) == 1:
        for prior_y in [years[0] - 1, years[0] - 2]:
            prior_period = PeriodFilter(period_type=PeriodType.YEAR, year=prior_y)
            prior_regular = store.get_regular(prior_period)
            if not prior_regular.empty:
                prior_monthly = _monthly_groups(prior_regular)
                for m in prior_monthly:
                    by_ym[(m["year"], m["month_num"])] = m
                if prior_y not in years:
                    years.append(prior_y)
        years = sorted(years)
    elif len(years) == 2:
        # Try to fetch one more prior year
        prior_y = years[0] - 1
        prior_period = PeriodFilter(period_type=PeriodType.YEAR, year=prior_y)
        prior_regular = store.get_regular(prior_period)
        if not prior_regular.empty:
            prior_monthly = _monthly_groups(prior_regular)
            for m in prior_monthly:
                by_ym[(m["year"], m["month_num"])] = m
            if prior_y not in years:
                years.insert(0, prior_y)

    # Build multi-year comparison rows
    # Only include months where the latest year has data (partial-year safe)
    latest_months = {m["month_num"] for m in monthly if m["year"] == latest_year} if latest_year else set()

    yoy_comparison = []
    for mn in range(1, 13):
        if latest_year and mn not in latest_months:
            # Check if ANY year has data for this month
            has_any = any(by_ym.get((y, mn)) for y in years)
            if not has_any:
                continue
        row = {"month_label": _MONTH_NAMES[mn], "month_num": mn}
        for y in years:
            d = by_ym.get((y, mn))
            row[f"y{y}_revenue"] = d["revenue"] if d else None
            row[f"y{y}_profit"] = d["profit"] if d else None
            row[f"y{y}_margin"] = round(d["margin"], 1) if d else None
            row[f"y{y}_units"] = d["units"] if d else None
            row[f"y{y}_full_price_pct"] = round(d["full_price_pct"], 1) if d else None
        # Change vs prior year (latest vs second-latest)
        if len(years) >= 2:
            d_cur = by_ym.get((years[-1], mn))
            d_prev = by_ym.get((years[-2], mn))
            row["revenue_change_pct"] = pct_change(d_cur["revenue"], d_prev["revenue"]) if d_cur and d_prev else None
            row["profit_change_pct"] = pct_change(d_cur["profit"], d_prev["profit"]) if d_cur and d_prev else None
            row["margin_change_pts"] = round(d_cur["margin"] - d_prev["margin"], 1) if d_cur and d_prev else None
        yoy_comparison.append(row)

    # Also keep backward-compatible y1/y2 fields for existing frontend code
    if len(years) >= 2:
        for row in yoy_comparison:
            row["y1"] = years[-2]
            row["y2"] = years[-1]
            row["y1_revenue"] = row.get(f"y{years[-2]}_revenue")
            row["y1_profit"] = row.get(f"y{years[-2]}_profit")
            row["y1_margin"] = row.get(f"y{years[-2]}_margin")
            row["y1_units"] = row.get(f"y{years[-2]}_units")
            row["y1_full_price_pct"] = row.get(f"y{years[-2]}_full_price_pct")
            row["y2_revenue"] = row.get(f"y{years[-1]}_revenue")
            row["y2_profit"] = row.get(f"y{years[-1]}_profit")
            row["y2_margin"] = row.get(f"y{years[-1]}_margin")
            row["y2_units"] = row.get(f"y{years[-1]}_units")
            row["y2_full_price_pct"] = row.get(f"y{years[-1]}_full_price_pct")

    return sanitize_for_json({
        "period_label": label,
        "months": monthly,
        "totals": totals,
        "best_month": {"label": best["label"], "revenue": best["revenue"]} if best else None,
        "worst_month": {"label": worst["label"], "revenue": worst["revenue"]} if worst else None,
        "yoy_comparison": yoy_comparison,
        "comparison_years": years,
    })


# ---------------------------------------------------------------------------
# Store Performance
# ---------------------------------------------------------------------------

def store_performance(store: DataStore, period: PeriodFilter | None) -> dict:
    """Store-level performance rankings with Same-Store Sales Growth."""
    from app.data.schemas import PeriodType
    regular = store.get_regular(period)
    label = period.label if period else "All Time"

    if regular.empty:
        return sanitize_for_json({"period_label": label, "empty": True})

    total_rev = float(regular["actual_revenue"].sum())

    store_agg = regular.groupby("store_clean", observed=True).agg(
        revenue=("actual_revenue", "sum"),
        profit=("net_profit", "sum"),
        cost=("cost", "sum"),
        units=("quantity", "sum"),
        transactions=("receipt_id", "nunique"),
        customers=("customer_id", "nunique"),
        discounts=("discounts", "sum"),
    ).reset_index().sort_values("revenue", ascending=False)

    avg_margin = safe_divide(float(regular["net_profit"].sum()), total_rev) * 100

    # Same-Store Sales Growth: compare each store's revenue to same months last year
    current_months = set(zip(regular["year"].astype(int), regular["month"].astype(int)))
    prior_months = {(y - 1, m) for y, m in current_months}
    # Build prior period filter for the same months one year ago
    prior_regular = pd.DataFrame()
    if prior_months:
        all_data = store.get_regular(PeriodFilter(period_type=PeriodType.ALL))
        if not all_data.empty:
            ym_pairs = all_data["year"].astype(int) * 100 + all_data["month"].astype(int)
            prior_ym_set = {y * 100 + m for y, m in prior_months}
            prior_regular = all_data[ym_pairs.isin(prior_ym_set)]

    prior_store_rev = {}
    if not prior_regular.empty:
        pr_agg = prior_regular.groupby("store_clean", observed=True)["actual_revenue"].sum()
        prior_store_rev = pr_agg.to_dict()
    prior_total = sum(prior_store_rev.values()) if prior_store_rev else 0

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
        top_brand = store_data.groupby("brand_clean", observed=True)["actual_revenue"].sum().idxmax() if not store_data.empty else ""
        top_cat = store_data.groupby("category_clean", observed=True)["actual_revenue"].sum().idxmax() if not store_data.empty else ""

        # SSSG: same-store sales growth vs prior year same months
        prior_rev = prior_store_rev.get(r["store_clean"])
        sssg = pct_change(rev, prior_rev) if prior_rev else None

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
            "sssg": round(sssg, 1) if sssg is not None else None,
            "prior_revenue": prior_rev,
        })

    top_perf = stores_list[0]["name"] if stores_list else ""
    bottom_margins = sorted(stores_list, key=lambda s: s["margin"])
    bottom_perf = bottom_margins[0]["name"] if bottom_margins else ""

    # Company-wide SSSG
    company_sssg = round(pct_change(total_rev, prior_total), 1) if prior_total > 0 else None

    return sanitize_for_json({
        "period_label": label,
        "date_range": store.date_range(period),
        "stores": stores_list,
        "company_avg_margin": round(avg_margin, 1),
        "company_sssg": company_sssg,
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
        first_label = monthly[0]["label"]
        last_label = monthly[-1]["label"]
        delta = last_margin - first_margin
        if delta > 1:
            key_insights.append({"type": "success", "title": "Margin Improved", "detail": f"{delta:.1f} pts from {first_label} ({first_margin:.1f}%) to {last_label} ({last_margin:.1f}%)"})
        elif delta < -1:
            key_insights.append({"type": "warning", "title": "Margin Declined", "detail": f"{abs(delta):.1f} pts from {first_label} ({first_margin:.1f}%) to {last_label} ({last_margin:.1f}%)"})
        else:
            key_insights.append({"type": "info", "title": "Margin Stable", "detail": f"Less than 1 pt change from {first_label} to {last_label}"})

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

    # YoY comparison — align to same months present in current year
    # so partial-year 2026 (e.g. Jan-Mar) compares against Jan-Mar of prior year
    yoy = None
    current_months = {int(m["month_num"]) for m in monthly}
    prev_period = PeriodFilter(PeriodType.YEAR, year=year - 1)
    prev_regular = store.get_regular(prev_period)
    if not prev_regular.empty:
        # Filter prior year to only the months present in current year
        prev_regular = prev_regular[prev_regular["month"].isin(current_months)]
    if not prev_regular.empty:
        prev_rev = float(prev_regular["actual_revenue"].sum())
        prev_profit = float(prev_regular["net_profit"].sum())
        prev_units = int(prev_regular["quantity"].sum())
        prev_margin = round(safe_divide(prev_profit, prev_rev) * 100, 1)
        rev_per_unit = safe_divide(revenue, units)
        prev_rev_per_unit = safe_divide(prev_rev, prev_units)
        # What profit would have been at last year's margin on this year's revenue
        profit_at_old_margin = revenue * (prev_margin / 100)
        margin_impact = profit - profit_at_old_margin
        yoy = {
            "prev_year": year - 1,
            "revenue_change_pct": pct_change(revenue, prev_rev),
            "prev_revenue": prev_rev,
            "profit_change_pct": pct_change(profit, prev_profit),
            "prev_profit": prev_profit,
            "margin_current": round(margin, 1),
            "margin_prev": prev_margin,
            "margin_change_pts": round(margin - prev_margin, 1),
            "margin_impact_dollars": round(margin_impact, 0),
            "profit_at_old_margin": round(profit_at_old_margin, 0),
            "rev_per_unit_change_pct": pct_change(rev_per_unit, prev_rev_per_unit),
            "rev_per_unit_current": round(rev_per_unit, 2),
            "rev_per_unit_prev": round(prev_rev_per_unit, 2),
        }
        # Add YoY margin insight
        yoy_margin_delta = round(margin - prev_margin, 1)
        if yoy_margin_delta > 0.5:
            key_insights.insert(0, {"type": "success", "title": f"Margin Up vs {year - 1}",
                "detail": f"Blended margin {round(margin, 1)}% vs {prev_margin}% in {year - 1} (+{yoy_margin_delta} pts year-over-year)"})
        elif yoy_margin_delta < -0.5:
            key_insights.insert(0, {"type": "warning", "title": f"Margin Down vs {year - 1}",
                "detail": f"Blended margin {round(margin, 1)}% vs {prev_margin}% in {year - 1} ({yoy_margin_delta} pts year-over-year)"})
        else:
            key_insights.insert(0, {"type": "info", "title": f"Margin Flat vs {year - 1}",
                "detail": f"Blended margin {round(margin, 1)}% vs {prev_margin}% in {year - 1} (unchanged)"})

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
