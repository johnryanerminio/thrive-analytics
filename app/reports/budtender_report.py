"""
Master Budtender Performance Report — Sales Score (0-100) with tier classification.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.data.store import DataStore
from app.data.schemas import PeriodFilter
from app.analytics.budtenders import compute_sales_scores, budtender_summary
from app.excel.writer import ExcelWriter
from app.excel.styles import SECTION_FONT


BT_COLS = [
    ("budtender", "text", "Budtender"),
    ("store_clean", "text", "Store"),
    ("sales_score", "number", "Sales Score"),
    ("tier", "text", "Tier"),
    ("num_transactions", "number", "Transactions"),
    ("total_sales", "currency", "Total Sales"),
    ("avg_cart_value", "currency", "Avg Cart"),
    ("avg_units_per_cart", "decimal", "Units/Cart"),
    ("pct_sales_discounted", "percent", "Discount %"),
    ("face_to_face_pct", "percent", "F2F %"),
]


def generate_json(store: DataStore, period: PeriodFilter | None = None) -> dict:
    if store.bt_df is None:
        return {"error": "No budtender data available"}

    sales_df = store.get_sales(period)
    bt_scored = compute_sales_scores(store.bt_df, sales_df)
    summary = budtender_summary(bt_scored)

    # Clean NaN values before JSON serialization
    bt_clean = bt_scored.fillna({"Role": "", "store": "", "store_clean": ""}).fillna(0)

    by_store = {}
    for s in sorted(bt_clean["store_clean"].dropna().unique()):
        if not s:
            continue
        store_bt = bt_clean[bt_clean["store_clean"] == s]
        by_store[s] = store_bt.to_dict("records")

    return {
        "date_range": store.date_range(period),
        "summary": summary,
        "all_rankings": bt_clean.to_dict("records"),
        "by_store": by_store,
    }


def generate_excel(
    store: DataStore,
    output_path: str | Path,
    period: PeriodFilter | None = None,
) -> Path:
    data = generate_json(store, period)
    if "error" in data:
        raise ValueError(data["error"])

    ew = ExcelWriter()
    s = data["summary"]

    # Executive Summary
    ws = ew.add_sheet("Executive Summary")
    ew.write_title(ws, "THRIVE CANNABIS",
                   f"Budtender Performance Report  |  {data['date_range']}")

    row = ew.write_section(ws, 4, "TEAM OVERVIEW")
    row = ew.write_kpi_row(ws, row, [
        (s["total_budtenders"], "TOTAL BUDTENDERS", "number"),
        (s["avg_sales_score"], "AVG SALES SCORE", "number"),
        (s["top_performers"], "TOP PERFORMERS", "number"),
        (s["needs_coaching"], "NEEDS COACHING", "number"),
    ])

    # All Rankings
    ws2 = ew.add_sheet("All Rankings")
    ew.write_table(ws2, 1, BT_COLS, data["all_rankings"],
                   highlight_fn=lambda i, r: "gold" if r.get("tier") == "Top Performer" else ("warning" if r.get("tier") == "Needs Coaching" else None))

    # Store tabs
    for store_name, bt_list in data["by_store"].items():
        if not bt_list:
            continue
        short = store_name.replace("Thrive ", "").replace("Cannabis ", "")[:20]
        ws_s = ew.add_sheet(short)
        ew.write_table(ws_s, 1, BT_COLS, bt_list,
                       highlight_fn=lambda i, r: "gold" if i < 3 else None)

    return ew.save(output_path)
