"""
Master Deal Performance Report — Deal legend, type summary, top deals, by store.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.data.store import DataStore
from app.data.schemas import PeriodFilter
from app.analytics.deals import deal_type_summary, deal_summary, deal_summary_by_store, expand_deals
from app.excel.writer import ExcelWriter
from app.excel.styles import SECTION_FONT


DEAL_LEGEND = [
    ("NO DEAL", "Items sold at full price - no discount applied"),
    ("BUNDLE", "Multi-buy deals: BOGO, B1G1, 2 FOR $X, 3/$X, 4/$X, 5/$X, etc."),
    ("PERCENT OFF", "Percentage discounts: 10% OFF, 20% OFF, 25% OFF, etc."),
    ("CUSTOMER DISCOUNT", "Customer-type discounts: Senior, Veteran, Military, Industry, Medical, VIP, Employee"),
    ("PRICE DEAL", "Fixed price deals: 2 FOR $25, Eighths FOR $X, etc."),
    ("OTHER", "All other promotional deals not matching above categories"),
]


def generate_json(store: DataStore, period: PeriodFilter | None = None) -> dict:
    regular = store.get_regular(period)
    date_range = store.date_range(period)

    # Expand deals once, reuse for both summaries
    expanded = expand_deals(regular)
    return {
        "date_range": date_range,
        "deal_types": deal_type_summary(regular),
        "top_deals": deal_summary(regular, top_n=50, _expanded=expanded),
        "by_store": deal_summary_by_store(regular, top_n=10, _expanded=expanded),
    }


def generate_excel(
    store: DataStore,
    output_path: str | Path,
    period: PeriodFilter | None = None,
) -> Path:
    data = generate_json(store, period)
    ew = ExcelWriter()

    # Deal Summary with legend
    ws = ew.add_sheet("Deal Summary")
    ew.write_title(ws, "THRIVE CANNABIS", f"Deal Performance Report  |  {data['date_range']}")

    row = ew.write_section(ws, 4, "DEAL CLASSIFICATION KEY")
    row = ew.write_legend(ws, row, DEAL_LEGEND)

    row = ew.write_section(ws, row, "PERFORMANCE BY DEAL TYPE")
    ew.write_table(ws, row, [
        ("deal_type", "text", "Deal Type"),
        ("transactions", "number", "Transactions"),
        ("units", "number", "Units"),
        ("full_price_revenue", "currency", "Full Price Revenue"),
        ("discounts", "currency", "Discounts Given"),
        ("actual_revenue", "currency", "Actual Revenue"),
        ("discount_rate", "percent", "Discount Rate"),
        ("margin", "percent", "Margin"),
        ("net_profit", "currency", "Net Profit"),
    ], data["deal_types"], show_total=True, freeze=False)

    # Top 50 Deals
    if data["top_deals"]:
        deal_cols = [
            ("deal_name", "text", "Deal Name"),
            ("times_used", "number", "Times Used"),
            ("units", "number", "Units"),
            ("revenue", "currency", "Revenue"),
            ("discounts", "currency", "Discounts"),
            ("margin", "percent", "Margin"),
        ]
        ws2 = ew.add_sheet("Top 50 Deals")
        ew.write_table(ws2, 1, deal_cols, data["top_deals"],
                       highlight_fn=lambda i, r: "gold" if i < 10 else None)

        # By store tabs
        for store_name, deals in data["by_store"].items():
            if not deals:
                continue
            short = store_name.replace("Thrive ", "").replace("Cannabis ", "")[:12]
            ws_s = ew.add_sheet(f"Top 10 - {short}")
            ew.write_table(ws_s, 1, deal_cols, deals,
                           highlight_fn=lambda i, r: "gold" if i < 3 else None)

    return ew.save(output_path)
