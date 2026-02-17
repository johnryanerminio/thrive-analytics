"""
Brand-Facing Inverse Report — What a brand sees about their performance at Thrive.

9 Tabs: Executive Summary, Distribution Scorecard, Share of Category,
Velocity Benchmarking, Store Gap Analysis, Product Mix, Pricing Consistency,
Promotional Effectiveness, Growth Opportunities.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.data.store import DataStore
from app.data.schemas import PeriodFilter
from app.analytics.common import safe_divide, calc_margin, sanitize_for_json, fillna_numeric
from app.analytics.margin import brand_margin_summary
from app.analytics.velocity import velocity_by_category, share_of_category, monthly_trend, share_of_category_trend
from app.analytics.deals import expand_deals, promo_lift
from app.analytics.recommendations import brand_facing_recommendations
from app.excel.writer import ExcelWriter
from app.excel.styles import SECTION_FONT


# =====================================================================
# JSON generation
# =====================================================================

def generate_json(
    store: DataStore,
    brand_name: str,
    period: PeriodFilter | None = None,
) -> dict:
    """Full brand-facing report as JSON."""
    brand_df = store.get_brand(brand_name, period)
    regular_df = store.get_regular(period)
    date_range = store.date_range(period)

    if brand_df.empty:
        return {"error": f"No data for brand '{brand_name}'", "brand": brand_name}

    summary = brand_margin_summary(brand_df)
    summary["brand"] = brand_name
    summary["date_range"] = date_range

    all_stores = sorted(regular_df["store_clean"].dropna().unique())
    brand_stores = sorted(brand_df["store_clean"].dropna().unique())

    # Share of category
    soc = share_of_category(brand_df, regular_df)

    # Primary category
    primary_category = soc[0]["category"] if soc else "UNKNOWN"
    summary["primary_category"] = primary_category

    # Velocity
    vel_by_cat = velocity_by_category(brand_df, regular_df)

    # Store coverage
    summary["store_coverage"] = f"{len(brand_stores)}/{len(all_stores)}"
    summary["stores_present"] = brand_stores
    summary["stores_missing"] = sorted(set(all_stores) - set(brand_stores))

    # Velocity rank
    cat_df = regular_df[regular_df["category_clean"] == primary_category]
    days = max((cat_df["sale_date"].max() - cat_df["sale_date"].min()).days + 1, 1) if len(cat_df) > 0 else 1
    brand_vel = cat_df.groupby("brand_clean", observed=True)["quantity"].sum() / days
    brand_vel = brand_vel.sort_values(ascending=False)
    ranked = brand_vel.index.tolist()
    summary["velocity_rank"] = ranked.index(brand_name) + 1 if brand_name in ranked else 0
    summary["velocity_total"] = len(ranked)

    # 1. Distribution Scorecard
    distribution = _distribution_scorecard(brand_df, regular_df, all_stores)

    # 2. Share of category trend
    soc_trend = {}
    for entry in soc:
        cat = entry["category"]
        soc_trend[cat] = share_of_category_trend(brand_df, regular_df, cat)

    # 3. Velocity benchmarking (already have vel_by_cat)

    # 4. Store gap analysis
    store_gaps = _store_gap_analysis(brand_df, regular_df, all_stores, brand_stores)

    # 5. Product mix
    product_mix = _product_mix(brand_df)

    # 6. Pricing consistency
    pricing = _pricing_consistency(brand_df)

    # 7. Promotional effectiveness
    promo = _promotional_effectiveness(brand_df)

    # 8. Growth opportunities
    growth = brand_facing_recommendations(
        brand_name, brand_df, regular_df,
        {"stores_present": brand_stores, "stores_missing": summary["stores_missing"]},
        vel_by_cat,
    )

    # Trend
    trend = monthly_trend(brand_df)

    return sanitize_for_json({
        "brand": brand_name,
        "date_range": date_range,
        "period_label": period.label if period else "All Time",
        "summary": summary,
        "distribution": distribution,
        "share_of_category": soc,
        "share_of_category_trend": soc_trend,
        "velocity_by_category": vel_by_cat,
        "store_gaps": store_gaps,
        "product_mix": product_mix,
        "pricing_consistency": pricing,
        "promotional_effectiveness": promo,
        "growth_opportunities": growth,
        "trend": trend,
    })


def _distribution_scorecard(
    brand_df: pd.DataFrame,
    regular_df: pd.DataFrame,
    all_stores: list[str],
) -> list[dict]:
    """Which stores carry the brand, SKU count per store, revenue."""
    result = []
    for s in all_stores:
        store_brand = brand_df[brand_df["store_clean"] == s]
        store_all = regular_df[regular_df["store_clean"] == s]

        if store_brand.empty:
            result.append({
                "store": s,
                "carries_brand": False,
                "sku_count": 0,
                "revenue": 0,
                "units": 0,
                "store_total_revenue": float(store_all["actual_revenue"].sum()),
                "brand_share_pct": 0,
            })
        else:
            rev = store_brand["actual_revenue"].sum()
            store_rev = store_all["actual_revenue"].sum()
            result.append({
                "store": s,
                "carries_brand": True,
                "sku_count": store_brand["product"].nunique(),
                "revenue": float(rev),
                "units": int(store_brand["quantity"].sum()),
                "store_total_revenue": float(store_rev),
                "brand_share_pct": round(safe_divide(rev, store_rev) * 100, 1),
            })
    return result


def _store_gap_analysis(
    brand_df: pd.DataFrame,
    regular_df: pd.DataFrame,
    all_stores: list[str],
    brand_stores: list[str],
) -> list[dict]:
    """High category demand + low/no brand presence = opportunity."""
    brand_cats = brand_df["category_clean"].unique()
    missing_stores = set(all_stores) - set(brand_stores)

    gaps = []
    for s in sorted(missing_stores):
        store_df = regular_df[regular_df["store_clean"] == s]
        for cat in brand_cats:
            cat_rev = store_df[store_df["category_clean"] == cat]["actual_revenue"].sum()
            if cat_rev > 0:
                gaps.append({
                    "store": s,
                    "category": cat,
                    "category_revenue_at_store": float(cat_rev),
                    "opportunity": "Brand not carried",
                })

    # Also check stores where brand IS present but specific categories missing
    for s in brand_stores:
        store_brand = brand_df[brand_df["store_clean"] == s]
        brand_cats_at_store = set(store_brand["category_clean"].unique())
        store_df = regular_df[regular_df["store_clean"] == s]
        for cat in brand_cats:
            if cat not in brand_cats_at_store:
                cat_rev = store_df[store_df["category_clean"] == cat]["actual_revenue"].sum()
                if cat_rev > 1000:
                    gaps.append({
                        "store": s,
                        "category": cat,
                        "category_revenue_at_store": float(cat_rev),
                        "opportunity": "Category not carried at this store",
                    })

    return sorted(gaps, key=lambda x: x["category_revenue_at_store"], reverse=True)


def _product_mix(brand_df: pd.DataFrame) -> dict:
    """Top/bottom SKUs + expansion opportunities."""
    agg = brand_df.groupby("product", observed=True).agg(
        units=("quantity", "sum"),
        revenue=("actual_revenue", "sum"),
        cost=("cost", "sum"),
        profit=("net_profit", "sum"),
        stores=("store_clean", "nunique"),
        transactions=("receipt_id", "nunique"),
    ).reset_index()
    agg["margin"] = ((agg["revenue"] - agg["cost"]) / agg["revenue"].replace(0, np.nan) * 100).round(1)
    agg = agg.sort_values("revenue", ascending=False)

    total_stores = brand_df["store_clean"].nunique()

    top = fillna_numeric(agg.head(20)).to_dict("records")
    bottom = fillna_numeric(agg.tail(10)).to_dict("records") if len(agg) > 20 else []

    # Expansion: products at some stores but not all
    partial = agg[(agg["stores"] < total_stores) & (agg["stores"] >= 2)].head(10)
    expansion = []
    for _, row in partial.iterrows():
        present = set(brand_df[brand_df["product"] == row["product"]]["store_clean"].unique())
        absent = set(brand_df["store_clean"].unique()) - present
        expansion.append({
            "product": row["product"],
            "current_stores": int(row["stores"]),
            "total_stores": total_stores,
            "missing_stores": sorted(absent),
            "revenue": float(row["revenue"]),
        })

    return {"top": top, "bottom": bottom, "expansion": expansion}


def _pricing_consistency(brand_df: pd.DataFrame) -> list[dict]:
    """Same product price across stores (min/max/avg/std dev)."""
    # Average price per unit per product per store
    agg = brand_df.groupby(["product", "store_clean"], observed=True).agg(
        avg_price=("actual_revenue", lambda x: x.sum() / brand_df.loc[x.index, "quantity"].sum() if brand_df.loc[x.index, "quantity"].sum() > 0 else 0),
    ).reset_index()

    # Products sold at multiple stores
    multi = agg.groupby("product", observed=True).filter(lambda x: len(x) >= 2)
    if multi.empty:
        return []

    pricing = multi.groupby("product", observed=True)["avg_price"].agg(
        ["min", "max", "mean", "std", "count"]
    ).reset_index()
    pricing.columns = ["product", "min_price", "max_price", "avg_price", "std_dev", "store_count"]
    pricing["price_range"] = pricing["max_price"] - pricing["min_price"]
    pricing["range_pct"] = (pricing["price_range"] / pricing["avg_price"].replace(0, np.nan) * 100).round(1)
    pricing = pricing.sort_values("range_pct", ascending=False)

    return fillna_numeric(pricing.head(30)).to_dict("records")


def _promotional_effectiveness(brand_df: pd.DataFrame) -> dict:
    """Discounted vs full-price velocity per deal."""
    lift = promo_lift(brand_df)

    # Per-deal effectiveness
    expanded = expand_deals(brand_df)
    if expanded.empty:
        return {"lift": lift, "by_deal": []}

    deal_agg = expanded.groupby("deal_name", observed=True).agg(
        uses=("receipt_id", "nunique"),
        revenue=("revenue", "sum"),
        discounts=("discounts", "sum"),
        units=("quantity", "sum"),
        cost=("cost", "sum"),
    ).reset_index()
    deal_agg["margin"] = ((deal_agg["revenue"] - deal_agg["cost"]) / deal_agg["revenue"].replace(0, np.nan) * 100).round(1)
    deal_agg["discount_depth"] = (deal_agg["discounts"] / (deal_agg["revenue"] + deal_agg["discounts"]).replace(0, np.nan) * 100).round(1)
    deal_agg = deal_agg.sort_values("uses", ascending=False)

    return {
        "lift": lift,
        "by_deal": fillna_numeric(deal_agg.head(20)).to_dict("records"),
    }


# =====================================================================
# Excel rendering
# =====================================================================

def generate_excel(
    store: DataStore,
    brand_name: str,
    output_path: str | Path,
    period: PeriodFilter | None = None,
) -> Path:
    """Generate the brand-facing Excel report."""
    data = generate_json(store, brand_name, period)
    if "error" in data:
        raise ValueError(data["error"])

    ew = ExcelWriter()
    s = data["summary"]
    brand = data["brand"]
    dr = data["date_range"]

    # ── Executive Summary ──────────────────────────────────────────
    ws = ew.add_sheet("Executive Summary")
    ew.write_title(ws, f"{brand.upper()} AT THRIVE CANNABIS",
                   f"Brand Performance Report  |  {dr}")

    row = ew.write_section(ws, 4, "REVENUE & MARGIN")
    row = ew.write_kpi_row(ws, row, [
        (s["total_revenue"], "REVENUE AT THRIVE", "currency"),
        (s["overall_margin"], "BLENDED MARGIN", "percent"),
        (s["total_units"], "UNITS SOLD", "number"),
        (s["total_profit"], "NET PROFIT", "currency"),
    ])

    row = ew.write_section(ws, row, "MARKET POSITION")
    from app.excel.formatters import add_kpi_card
    add_kpi_card(ws, row, 1, s["store_coverage"], "STORE COVERAGE", "text")
    vr = f"#{s['velocity_rank']} of {s['velocity_total']}" if s["velocity_rank"] > 0 else "N/A"
    add_kpi_card(ws, row, 3, vr, f"VELOCITY RANK ({s['primary_category']})", "text")
    add_kpi_card(ws, row, 5, s["pct_full_price"], "SOLD FULL PRICE", "percent")
    add_kpi_card(ws, row, 7, s["avg_discount_rate"], "AVG DISCOUNT RATE", "percent")

    # ── Distribution Scorecard ─────────────────────────────────────
    ws_d = ew.add_sheet("Distribution Scorecard")
    ws_d.cell(row=1, column=1).value = f"{brand} Distribution Across Stores"
    ws_d.cell(row=1, column=1).font = SECTION_FONT
    ew.write_table(ws_d, 3, [
        ("store", "text", "Store"),
        ("carries_brand", "text", "Carried"),
        ("sku_count", "number", "SKU Count"),
        ("revenue", "currency", "Brand Revenue"),
        ("units", "number", "Units"),
        ("store_total_revenue", "currency", "Store Total Revenue"),
        ("brand_share_pct", "percent", "Brand Share %"),
    ], data["distribution"],
       highlight_fn=lambda i, r: "warning" if not r.get("carries_brand") else ("gold" if r.get("brand_share_pct", 0) > 5 else None))

    # ── Share of Category ──────────────────────────────────────────
    if data["share_of_category"]:
        ws_soc = ew.add_sheet("Share of Category")
        ws_soc.cell(row=1, column=1).value = f"{brand} Share of Category Revenue"
        ws_soc.cell(row=1, column=1).font = SECTION_FONT
        ew.write_table(ws_soc, 3, [
            ("category", "text", "Category"),
            ("brand_revenue", "currency", "Brand Revenue"),
            ("category_revenue", "currency", "Category Total"),
            ("revenue_share_pct", "percent", "Revenue Share %"),
            ("brand_units", "number", "Brand Units"),
            ("category_units", "number", "Category Units"),
            ("units_share_pct", "percent", "Units Share %"),
        ], data["share_of_category"],
           highlight_fn=lambda i, r: "gold" if r.get("revenue_share_pct", 0) > 10 else None)

    # ── Velocity Benchmarking ──────────────────────────────────────
    if data["velocity_by_category"]:
        ws_v = ew.add_sheet("Velocity Benchmarking")
        ws_v.cell(row=1, column=1).value = f"{brand} Velocity vs Category Average"
        ws_v.cell(row=1, column=1).font = SECTION_FONT
        ew.write_table(ws_v, 3, [
            ("category", "text", "Category"),
            ("brand_units_per_day", "decimal", "Brand Units/Day"),
            ("category_avg_units_per_day", "decimal", "Cat Avg Units/Day"),
            ("velocity_index", "number", "Velocity Index"),
            ("brand_rev_per_unit", "currency", "Brand $/Unit"),
            ("category_rev_per_unit", "currency", "Cat $/Unit"),
            ("brands_in_category", "number", "Brands"),
        ], data["velocity_by_category"],
           highlight_fn=lambda i, r: "gold" if r.get("velocity_index", 0) > 120 else ("warning" if r.get("velocity_index", 0) < 80 else None))

    # ── Store Gap Analysis ─────────────────────────────────────────
    if data["store_gaps"]:
        ws_g = ew.add_sheet("Store Gap Analysis")
        ws_g.cell(row=1, column=1).value = f"{brand} Store & Category Gaps"
        ws_g.cell(row=1, column=1).font = SECTION_FONT
        ew.write_table(ws_g, 3, [
            ("store", "text", "Store"),
            ("category", "text", "Category"),
            ("category_revenue_at_store", "currency", "Category Revenue"),
            ("opportunity", "text", "Opportunity"),
        ], data["store_gaps"],
           highlight_fn=lambda i, r: "gold" if r.get("category_revenue_at_store", 0) > 50000 else None)

    # ── Product Mix ────────────────────────────────────────────────
    pm = data["product_mix"]
    ws_pm = ew.add_sheet("Product Mix")
    ws_pm.cell(row=1, column=1).value = f"{brand} Top Products"
    ws_pm.cell(row=1, column=1).font = SECTION_FONT
    prod_cols = [
        ("product", "text", "Product"),
        ("stores", "number", "Stores"),
        ("transactions", "number", "Transactions"),
        ("units", "number", "Units"),
        ("revenue", "currency", "Revenue"),
        ("margin", "percent", "Margin"),
        ("profit", "currency", "Profit"),
    ]
    last_row = ew.write_table(ws_pm, 3, prod_cols, pm["top"],
                              highlight_fn=lambda i, r: "gold" if i < 5 else None)

    if pm["expansion"]:
        ws_pm.cell(row=last_row + 1, column=1).value = "SKU EXPANSION OPPORTUNITIES"
        ws_pm.cell(row=last_row + 1, column=1).font = SECTION_FONT
        ew.write_table(ws_pm, last_row + 3, [
            ("product", "text", "Product"),
            ("current_stores", "number", "Current Stores"),
            ("total_stores", "number", "Total Stores"),
            ("revenue", "currency", "Current Revenue"),
        ], pm["expansion"])

    # ── Pricing Consistency ────────────────────────────────────────
    if data["pricing_consistency"]:
        ws_pc = ew.add_sheet("Pricing Consistency")
        ws_pc.cell(row=1, column=1).value = f"{brand} Price Variation Across Stores"
        ws_pc.cell(row=1, column=1).font = SECTION_FONT
        ew.write_table(ws_pc, 3, [
            ("product", "text", "Product"),
            ("store_count", "number", "Stores"),
            ("min_price", "currency", "Min Price"),
            ("max_price", "currency", "Max Price"),
            ("avg_price", "currency", "Avg Price"),
            ("std_dev", "currency", "Std Dev"),
            ("range_pct", "percent", "Range %"),
        ], data["pricing_consistency"],
           highlight_fn=lambda i, r: "warning" if r.get("range_pct", 0) > 20 else None)

    # ── Promotional Effectiveness ──────────────────────────────────
    promo = data["promotional_effectiveness"]
    ws_pe = ew.add_sheet("Promotional Effectiveness")
    ws_pe.cell(row=1, column=1).value = f"{brand} Promotional Analysis"
    ws_pe.cell(row=1, column=1).font = SECTION_FONT

    lift = promo["lift"]
    from app.excel.formatters import add_kpi_card as kpi
    kpi(ws_pe, 3, 1, lift["fp_units_per_day"], "FULL PRICE UNITS/DAY", "decimal")
    kpi(ws_pe, 3, 3, lift["disc_units_per_day"], "PROMO UNITS/DAY", "decimal")
    if lift.get("lift_pct") is not None:
        kpi(ws_pe, 3, 5, lift["lift_pct"], "PROMO LIFT %", "decimal")
    kpi(ws_pe, 3, 7, lift["fp_avg_revenue_per_unit"], "FP $/UNIT", "currency")

    if promo["by_deal"]:
        ew.write_table(ws_pe, 7, [
            ("deal_name", "text", "Deal Name"),
            ("uses", "number", "Uses"),
            ("units", "number", "Units"),
            ("revenue", "currency", "Revenue"),
            ("discounts", "currency", "Discounts"),
            ("discount_depth", "percent", "Discount Depth"),
            ("margin", "percent", "Margin"),
        ], promo["by_deal"],
           highlight_fn=lambda i, r: "warning" if r.get("margin", 100) < 40 else None)

    # ── Growth Opportunities ───────────────────────────────────────
    if data["growth_opportunities"]:
        ws_go = ew.add_sheet("Growth Opportunities")
        ew.write_title(ws_go, f"{brand.upper()} GROWTH OPPORTUNITIES",
                       f"Specific recommendations with store & SKU targets  |  {dr}")
        ew.write_recommendations(ws_go, 5, [
            {
                "severity": "green" if r.get("priority") == "high" else "info",
                "title": r["title"],
                "detail": r["detail"],
            }
            for r in data["growth_opportunities"]
        ])

    return ew.save(output_path)
