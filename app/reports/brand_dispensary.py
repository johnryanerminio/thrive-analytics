"""
Dispensary-side Brand Report — Enhanced with Trend, Share, Velocity, Discount Depth tabs.

JSON-first: generate_json() produces canonical data, generate_excel() renders it.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.data.store import DataStore
from app.data.schemas import PeriodFilter
from app.analytics.common import safe_divide, sanitize_for_json
from app.analytics.margin import brand_margin_summary, brand_category_breakdown, discount_depth_distribution
from app.analytics.deals import deal_summary
from app.analytics.velocity import velocity_metrics, velocity_by_category, share_of_category, monthly_trend, share_of_category_trend
from app.analytics.customers import brand_customer_count
from app.analytics.recommendations import dispensary_recommendations
from app.excel.writer import ExcelWriter


# =====================================================================
# JSON generation
# =====================================================================

def generate_json(
    store: DataStore,
    brand_name: str,
    period: PeriodFilter | None = None,
    comparison_period: PeriodFilter | None = None,
) -> dict:
    """Produce the full brand report as a JSON-serialisable dict."""
    brand_df = store.get_brand(brand_name, period)
    regular_df = store.get_regular(period)
    date_range = store.date_range(period)

    if brand_df.empty:
        return {"error": f"No data for brand '{brand_name}'", "brand": brand_name}

    cat_margin_lookup = store.category_margin_lookup(period)
    cat_rankings = store.brand_category_rankings(period)

    # Core margin summary
    summary = brand_margin_summary(brand_df)
    summary["unique_customers"] = brand_customer_count(brand_df)
    summary["brand"] = brand_name
    summary["date_range"] = date_range

    # Category breakdown
    cat_breakdown = brand_category_breakdown(brand_df, cat_margin_lookup, cat_rankings, brand_name)

    # Primary category info
    if len(cat_breakdown) > 0:
        primary = cat_breakdown.iloc[0]
        primary_category = primary["category_clean"]
        primary_cat_margin = cat_margin_lookup.get(primary_category, summary["overall_margin"])
        primary_rank = int(primary.get("rank", 0))
        primary_total = int(primary.get("total_brands", 0))
    else:
        primary_category = "UNKNOWN"
        primary_cat_margin = summary["overall_margin"]
        primary_rank = 0
        primary_total = 0

    summary["primary_category"] = primary_category
    summary["primary_cat_margin"] = primary_cat_margin
    summary["category_rank"] = primary_rank
    summary["category_total"] = primary_total
    summary["margin_vs_category"] = round(summary["overall_margin"] - primary_cat_margin, 1)

    # Velocity
    vel = velocity_metrics(brand_df, regular_df)
    vel_by_cat = velocity_by_category(brand_df, regular_df)
    summary["velocity_rank"] = _velocity_rank(brand_name, regular_df, primary_category)

    # Trend analysis
    trend = monthly_trend(brand_df)

    # Share of category
    soc = share_of_category(brand_df, regular_df)
    soc_trend = {}
    for cat_entry in soc:
        cat_name = cat_entry["category"]
        soc_trend[cat_name] = share_of_category_trend(brand_df, regular_df, cat_name)

    # Discount depth
    depth = discount_depth_distribution(brand_df)

    # Deals
    deals = deal_summary(brand_df, top_n=50)

    # Top products
    top_products = _top_products(brand_df, 25)

    # Products by store
    products_by_store = _products_by_store(brand_df, 15)

    # Store summary
    store_summary = _store_summary(brand_df)

    # Recommendations
    recs = dispensary_recommendations(
        brand_name, summary, cat_breakdown, primary_category, primary_cat_margin
    )

    # Comparison period
    comparison = None
    if comparison_period:
        comp_brand = store.get_brand(brand_name, comparison_period)
        if not comp_brand.empty:
            comp_summary = brand_margin_summary(comp_brand)
            comparison = {
                "period_label": comparison_period.label,
                "summary": comp_summary,
            }

    return sanitize_for_json({
        "brand": brand_name,
        "date_range": date_range,
        "period_label": period.label if period else "All Time",
        "summary": summary,
        "category_breakdown": cat_breakdown.fillna(0).to_dict("records"),
        "trend": trend,
        "share_of_category": soc,
        "share_of_category_trend": soc_trend,
        "discount_depth": depth,
        "velocity": vel,
        "velocity_by_category": vel_by_cat,
        "deals": deals,
        "top_products": top_products,
        "products_by_store": products_by_store,
        "store_summary": store_summary,
        "recommendations": recs,
        "comparison": comparison,
    })


def _velocity_rank(brand_name: str, regular_df: pd.DataFrame, category: str) -> int:
    """Rank this brand by units/day within its primary category."""
    cat_df = regular_df[regular_df["category_clean"] == category]
    days = max((cat_df["sale_date"].max() - cat_df["sale_date"].min()).days + 1, 1)
    brand_vel = cat_df.groupby("brand_clean")["quantity"].sum() / days
    brand_vel = brand_vel.sort_values(ascending=False)
    ranked = brand_vel.index.tolist()
    return ranked.index(brand_name) + 1 if brand_name in ranked else 0


def _top_products(brand_df: pd.DataFrame, n: int) -> list[dict]:
    agg = brand_df.groupby("product").agg(
        units=("quantity", "sum"),
        revenue=("actual_revenue", "sum"),
        cost=("cost", "sum"),
        profit=("net_profit", "sum"),
        transactions=("receipt_id", "nunique"),
    ).reset_index()
    agg["margin"] = ((agg["revenue"] - agg["cost"]) / agg["revenue"].replace(0, float("nan")) * 100).round(1)
    return agg.sort_values("revenue", ascending=False).head(n).fillna(0).to_dict("records")


def _products_by_store(brand_df: pd.DataFrame, n: int) -> dict[str, list[dict]]:
    result = {}
    for s in sorted(brand_df["store_clean"].dropna().unique()):
        sdf = brand_df[brand_df["store_clean"] == s]
        agg = sdf.groupby("product").agg(
            units=("quantity", "sum"),
            revenue=("actual_revenue", "sum"),
            cost=("cost", "sum"),
            profit=("net_profit", "sum"),
            transactions=("receipt_id", "nunique"),
        ).reset_index()
        agg["margin"] = ((agg["revenue"] - agg["cost"]) / agg["revenue"].replace(0, float("nan")) * 100).round(1)
        result[s] = agg.sort_values("revenue", ascending=False).head(n).fillna(0).to_dict("records")
    return result


def _store_summary(brand_df: pd.DataFrame) -> list[dict]:
    agg = brand_df.groupby("store_clean").agg(
        units=("quantity", "sum"),
        revenue=("actual_revenue", "sum"),
        cost=("cost", "sum"),
        profit=("net_profit", "sum"),
        discounts=("discounts", "sum"),
    ).reset_index()
    agg["margin"] = ((agg["revenue"] - agg["cost"]) / agg["revenue"].replace(0, float("nan")) * 100).round(1)
    agg["discount_rate"] = (agg["discounts"] / (agg["revenue"] + agg["discounts"]).replace(0, float("nan")) * 100).round(1)
    return agg.sort_values("revenue", ascending=False).fillna(0).to_dict("records")


# =====================================================================
# Excel rendering
# =====================================================================

def generate_excel(
    store: DataStore,
    brand_name: str,
    output_path: str | Path,
    period: PeriodFilter | None = None,
    comparison_period: PeriodFilter | None = None,
) -> Path:
    """Generate the full Excel brand report."""
    data = generate_json(store, brand_name, period, comparison_period)
    if "error" in data:
        raise ValueError(data["error"])

    ew = ExcelWriter()
    s = data["summary"]
    brand = data["brand"]
    date_range = data["date_range"]

    # ── Executive Summary ──────────────────────────────────────────
    ws = ew.add_sheet("Executive Summary")
    ew.write_title(ws, brand.upper(), f"Brand Performance Report  |  {date_range}  |  Prepared by Thrive Cannabis")

    row = ew.write_section(ws, 4, "SALES PERFORMANCE")
    row = ew.write_kpi_row(ws, row, [
        (s["total_units"], "UNITS SOLD", "number"),
        (s["total_revenue"], "TOTAL REVENUE", "currency"),
        (s["total_profit"], "NET PROFIT", "currency"),
        (s["overall_margin"], "OVERALL MARGIN", "percent"),
    ])

    row = ew.write_section(ws, row, "PRICING ANALYSIS")
    row = ew.write_kpi_row(ws, row, [
        (s["pct_full_price"], "% SOLD FULL PRICE", "percent"),
        (s["fp_margin"], "FULL PRICE MARGIN", "percent"),
        (s["disc_margin"], "DISCOUNTED MARGIN", "percent"),
        (s["avg_discount_rate"], "AVG DISCOUNT RATE", "percent"),
    ])

    row = ew.write_section(ws, row, "CATEGORY RANKING")
    rank_text = f"#{s['category_rank']} of {s['category_total']}" if s["category_rank"] > 0 else "N/A"
    from app.excel.formatters import add_kpi_card
    add_kpi_card(ws, row, 1, rank_text, f"RANK IN {s['primary_category']}", "text")
    add_kpi_card(ws, row, 3, s["primary_cat_margin"], f"{s['primary_category']} AVG MARGIN", "percent")
    ew.write_delta_kpi(ws, row, 5, s["margin_vs_category"], "PTS VS CATEGORY")

    # Unique customers + velocity rank
    add_kpi_card(ws, row, 7, s["unique_customers"], "UNIQUE CUSTOMERS", "number")
    row += 3

    # Key insight
    mvsc = s["margin_vs_category"]
    if mvsc < -10:
        insight = f"{brand} margin ({s['overall_margin']:.1f}%) is {abs(mvsc):.0f} pts BELOW {s['primary_category']} average ({s['primary_cat_margin']:.1f}%). Strong case for cost reduction."
    elif mvsc < 0:
        insight = f"{brand} margin ({s['overall_margin']:.1f}%) is slightly below {s['primary_category']} average ({s['primary_cat_margin']:.1f}%). Room for negotiation."
    elif s["pct_full_price"] < 30:
        insight = f"Only {s['pct_full_price']:.0f}% sells at full price. Heavy discounting required to move inventory."
    else:
        insight = f"{brand} performs well — ranked #{s['category_rank']} in {s['primary_category']} with {s['overall_margin']:.1f}% margin vs {s['primary_cat_margin']:.1f}% category average."
    ew.write_insight(ws, row, "KEY INSIGHT:", insight)

    # ── Trend Analysis (NEW) ──────────────────────────────────────
    if data["trend"]:
        ws_t = ew.add_sheet("Trend Analysis")
        ws_t.cell(row=1, column=1).value = f"{brand} Monthly Trend"
        ws_t.cell(row=1, column=1).font = __import__("app.excel.styles", fromlist=["SECTION_FONT"]).SECTION_FONT
        ew.write_table(ws_t, 3, [
            ("period", "text", "Month"),
            ("revenue", "currency", "Revenue"),
            ("revenue_change_pct", "decimal", "Rev Change %"),
            ("units", "number", "Units"),
            ("units_change_pct", "decimal", "Units Change %"),
            ("margin", "percent", "Margin"),
            ("margin_change_pts", "decimal", "Margin Chg (pts)"),
            ("transactions", "number", "Transactions"),
            ("profit", "currency", "Profit"),
        ], data["trend"], highlight_fn=lambda i, r: "gold" if (r.get("revenue_change_pct") or 0) > 10 else ("warning" if (r.get("revenue_change_pct") or 0) < -10 else None))

    # ── By Product Type ────────────────────────────────────────────
    cats = data["category_breakdown"]
    if len(cats) > 1:
        ws2 = ew.add_sheet("By Product Type")
        ws2.cell(row=1, column=1).value = f"{brand} Performance by Product Type"
        ws2.cell(row=1, column=1).font = __import__("app.excel.styles", fromlist=["SECTION_FONT"]).SECTION_FONT
        ew.write_table(ws2, 3, [
            ("category_clean", "text", "Product Type"),
            ("rank", "number", "Category Rank"),
            ("total_brands", "number", "Brands in Category"),
            ("units", "number", "Units"),
            ("revenue", "currency", "Revenue"),
            ("margin", "percent", "Margin"),
            ("category_avg_margin", "percent", "Category Avg"),
            ("vs_category", "percent", "vs Category"),
            ("profit", "currency", "Net Profit"),
        ], cats, highlight_fn=lambda i, r: "gold" if r.get("vs_category", 0) >= 0 else "warning")

    # ── Share of Category (NEW) ────────────────────────────────────
    if data["share_of_category"]:
        ws_soc = ew.add_sheet("Share of Category")
        ws_soc.cell(row=1, column=1).value = f"{brand} Share of Category"
        ws_soc.cell(row=1, column=1).font = __import__("app.excel.styles", fromlist=["SECTION_FONT"]).SECTION_FONT
        ew.write_table(ws_soc, 3, [
            ("category", "text", "Category"),
            ("brand_revenue", "currency", "Brand Revenue"),
            ("category_revenue", "currency", "Category Revenue"),
            ("revenue_share_pct", "percent", "Revenue Share %"),
            ("brand_units", "number", "Brand Units"),
            ("category_units", "number", "Category Units"),
            ("units_share_pct", "percent", "Units Share %"),
        ], data["share_of_category"], highlight_fn=lambda i, r: "gold" if r.get("revenue_share_pct", 0) > 10 else None)

    # ── Discount Depth (NEW) ───────────────────────────────────────
    if data["discount_depth"]:
        ws_dd = ew.add_sheet("Discount Depth")
        ws_dd.cell(row=1, column=1).value = f"{brand} Discount Depth Distribution"
        ws_dd.cell(row=1, column=1).font = __import__("app.excel.styles", fromlist=["SECTION_FONT"]).SECTION_FONT
        ew.write_table(ws_dd, 3, [
            ("tier", "text", "Discount Tier"),
            ("transactions", "number", "Transactions"),
            ("pct_of_transactions", "percent", "% of Transactions"),
            ("revenue", "currency", "Revenue"),
            ("avg_discount", "percent", "Avg Discount %"),
        ], data["discount_depth"])

    # ── Deal Performance ───────────────────────────────────────────
    if data["deals"]:
        ws3 = ew.add_sheet("Deal Performance")
        ws3.cell(row=1, column=1).value = f"Deals Used with {brand} Products"
        ws3.cell(row=1, column=1).font = __import__("app.excel.styles", fromlist=["SECTION_FONT"]).SECTION_FONT
        ew.write_table(ws3, 3, [
            ("deal_name", "text", "Deal Name"),
            ("times_used", "number", "Times Used"),
            ("units", "number", "Units"),
            ("revenue", "currency", "Revenue"),
            ("discounts", "currency", "Discounts"),
            ("avg_discount", "percent", "Discount %"),
            ("margin", "percent", "Margin"),
            ("profit", "currency", "Net Profit"),
        ], data["deals"], highlight_fn=lambda i, r: "warning" if r.get("margin", 100) < 40 else ("gold" if i < 3 else None))

    # ── Top Products ───────────────────────────────────────────────
    ws4 = ew.add_sheet("Top Products")
    ws4.cell(row=1, column=1).value = f"Top 25 {brand} Products (All Stores)"
    ws4.cell(row=1, column=1).font = __import__("app.excel.styles", fromlist=["SECTION_FONT"]).SECTION_FONT
    prod_cols = [
        ("product", "text", "Product"),
        ("transactions", "number", "Transactions"),
        ("units", "number", "Units"),
        ("revenue", "currency", "Revenue"),
        ("margin", "percent", "Margin"),
        ("profit", "currency", "Net Profit"),
    ]
    ew.write_table(ws4, 3, prod_cols, data["top_products"],
                   highlight_fn=lambda i, r: "gold" if i < 5 else None)

    # ── Products by Store ──────────────────────────────────────────
    for store_name, products in data["products_by_store"].items():
        if not products:
            continue
        short = store_name.replace("Thrive ", "").replace("Cannabis ", "")[:12]
        ws_s = ew.add_sheet(f"Products - {short}")
        ws_s.cell(row=1, column=1).value = f"Top {brand} Products at {store_name}"
        ws_s.cell(row=1, column=1).font = __import__("app.excel.styles", fromlist=["SECTION_FONT"]).SECTION_FONT
        ew.write_table(ws_s, 3, prod_cols, products,
                       highlight_fn=lambda i, r: "gold" if i < 3 else None)

    # ── By Store ───────────────────────────────────────────────────
    ws_st = ew.add_sheet("By Store")
    ws_st.cell(row=1, column=1).value = f"{brand} Performance by Store"
    ws_st.cell(row=1, column=1).font = __import__("app.excel.styles", fromlist=["SECTION_FONT"]).SECTION_FONT
    ew.write_table(ws_st, 3, [
        ("store_clean", "text", "Store"),
        ("units", "number", "Units"),
        ("revenue", "currency", "Revenue"),
        ("margin", "percent", "Margin"),
        ("discounts", "currency", "Discounts"),
        ("discount_rate", "percent", "Discount Rate"),
        ("profit", "currency", "Net Profit"),
    ], data["store_summary"])

    # ── Velocity Metrics (NEW) ─────────────────────────────────────
    if data["velocity_by_category"]:
        ws_v = ew.add_sheet("Velocity Metrics")
        ws_v.cell(row=1, column=1).value = f"{brand} Velocity vs Category Average"
        ws_v.cell(row=1, column=1).font = __import__("app.excel.styles", fromlist=["SECTION_FONT"]).SECTION_FONT
        ew.write_table(ws_v, 3, [
            ("category", "text", "Category"),
            ("brand_units_per_day", "decimal", "Brand Units/Day"),
            ("category_avg_units_per_day", "decimal", "Category Avg/Day"),
            ("velocity_index", "number", "Velocity Index"),
            ("brand_rev_per_unit", "currency", "Brand $/Unit"),
            ("category_rev_per_unit", "currency", "Category $/Unit"),
            ("brands_in_category", "number", "Brands"),
        ], data["velocity_by_category"],
           highlight_fn=lambda i, r: "gold" if r.get("velocity_index", 0) > 120 else ("warning" if r.get("velocity_index", 0) < 80 else None))

    # ── Comparison Period (NEW) ────────────────────────────────────
    if data.get("comparison"):
        ws_cp = ew.add_sheet("Comparison Period")
        comp = data["comparison"]
        cs = comp["summary"]
        ws_cp.cell(row=1, column=1).value = f"{brand} — Current vs {comp['period_label']}"
        ws_cp.cell(row=1, column=1).font = __import__("app.excel.styles", fromlist=["SECTION_FONT"]).SECTION_FONT

        comparison_data = [
            {"metric": "Revenue", "current": s["total_revenue"], "previous": cs["total_revenue"],
             "change": s["total_revenue"] - cs["total_revenue"]},
            {"metric": "Units", "current": s["total_units"], "previous": cs["total_units"],
             "change": s["total_units"] - cs["total_units"]},
            {"metric": "Margin %", "current": s["overall_margin"], "previous": cs["overall_margin"],
             "change": s["overall_margin"] - cs["overall_margin"]},
            {"metric": "Full Price %", "current": s["pct_full_price"], "previous": cs["pct_full_price"],
             "change": s["pct_full_price"] - cs["pct_full_price"]},
            {"metric": "Profit", "current": s["total_profit"], "previous": cs["total_profit"],
             "change": s["total_profit"] - cs["total_profit"]},
        ]
        ew.write_table(ws_cp, 3, [
            ("metric", "text", "Metric"),
            ("current", "currency", "Current Period"),
            ("previous", "currency", "Previous Period"),
            ("change", "currency", "Change"),
        ], comparison_data)

    # ── Recommendations ────────────────────────────────────────────
    ws_rec = ew.add_sheet("Recommendations")
    ew.write_title(ws_rec, "PRICING & PROMOTION RECOMMENDATIONS", f"{brand}  |  {date_range}")
    row = 5
    ew.write_recommendations(ws_rec, row, data["recommendations"])
    ws_rec.column_dimensions["A"].width = 80

    return ew.save(output_path)
