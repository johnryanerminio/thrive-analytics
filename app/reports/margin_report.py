"""
Master Margin Report — Full Price vs Discounted analysis by store/brand/category/deal type.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.data.store import DataStore
from app.data.schemas import PeriodFilter
from app.analytics.common import sanitize_for_json, fillna_numeric
from app.analytics.margin import company_margin_totals, margin_by_group
from app.excel.writer import ExcelWriter
from app.excel.styles import SECTION_FONT
from app.excel.formatters import add_kpi_card


MARGIN_COLS = [
    ("name", "text", "Name"),
    ("full_price_units", "number", "Full Price Units"),
    ("discounted_units", "number", "Discounted Units"),
    ("total_units", "number", "Total Units"),
    ("full_price_sales", "currency", "Full Price Sales"),
    ("discounted_sales", "currency", "Discounted Sales"),
    ("total_revenue", "currency", "Total Revenue"),
    ("pct_full_price", "percent", "% Full Price"),
    ("pct_discounted", "percent", "% Discounted"),
    ("full_price_margin", "percent", "FP Margin"),
    ("discounted_margin", "percent", "Disc Margin"),
    ("blended_margin", "percent", "Blended Margin"),
    ("net_profit", "currency", "Net Profit"),
]


def generate_json(store: DataStore, period: PeriodFilter | None = None) -> dict:
    regular = store.get_regular(period)
    date_range = store.date_range(period)
    totals = company_margin_totals(regular)

    return sanitize_for_json({
        "date_range": date_range,
        "totals": totals,
        "by_store": fillna_numeric(margin_by_group(regular, "store_clean")).to_dict("records"),
        "by_brand": fillna_numeric(margin_by_group(regular, "brand_clean")).to_dict("records"),
        "by_category": fillna_numeric(margin_by_group(regular, "category_clean")).to_dict("records"),
        "by_deal_type": fillna_numeric(margin_by_group(regular, "deal_type")).to_dict("records"),
    })


def generate_excel(
    store: DataStore,
    output_path: str | Path,
    period: PeriodFilter | None = None,
) -> Path:
    data = generate_json(store, period)
    t = data["totals"]
    ew = ExcelWriter()

    # Executive Summary
    ws = ew.add_sheet("Executive Summary")
    ew.write_title(ws, "THRIVE CANNABIS",
                   f"Margin Performance Report  |  {data['date_range']}  |  Generated {pd.Timestamp.now():%B %d, %Y}")

    row = ew.write_section(ws, 5, "REVENUE OVERVIEW")
    row = ew.write_kpi_row(ws, row, [
        (t["total_revenue"], "TOTAL REVENUE", "currency"),
        (t["full_price_sales"], "FULL PRICE SALES", "currency"),
        (t["discounted_sales"], "DISCOUNTED SALES", "currency"),
        (t["net_profit"], "NET PROFIT", "currency"),
    ])

    row = ew.write_section(ws, row, "SALES MIX")
    row = ew.write_kpi_row(ws, row, [
        (t["pct_full_price"], "% AT FULL PRICE", "percent"),
        (t["pct_discounted"], "% ON DISCOUNT", "percent"),
        (t["total_units"], "TOTAL UNITS", "number"),
    ])

    row = ew.write_section(ws, row, "MARGIN ANALYSIS")
    row = ew.write_kpi_row(ws, row, [
        (t["full_price_margin"], "FULL PRICE MARGIN", "percent"),
        (t["discounted_margin"], "DISCOUNTED MARGIN", "percent"),
        (t["blended_margin"], "BLENDED MARGIN", "percent"),
        (t["full_price_margin"] - t["discounted_margin"], "MARGIN GAP (pts)", "decimal"),
    ])

    # Data sheets
    for sheet_name, key in [("By Store", "by_store"), ("By Brand", "by_brand"),
                            ("By Category", "by_category"), ("By Deal Type", "by_deal_type")]:
        ws_d = ew.add_sheet(sheet_name)
        ew.write_table(ws_d, 1, MARGIN_COLS, data[key], show_total=True)

    return ew.save(output_path)
