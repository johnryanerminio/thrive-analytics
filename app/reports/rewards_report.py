"""
Master Rewards & Markout Report — Actual reward names by store + employee usage.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from app.data.store import DataStore
from app.data.schemas import PeriodFilter
from app.data.normalize import extract_reward_name
from app.analytics.common import safe_divide
from app.excel.writer import ExcelWriter
from app.excel.styles import SECTION_FONT


def generate_json(store: DataStore, period: PeriodFilter | None = None) -> dict:
    sales_df = store.get_sales(period)
    date_range = store.date_range(period)

    rewards_df = sales_df[sales_df["deals_upper"].str.contains("REWARD|POINT|REDEMPTION", na=False)].copy()
    rewards_df["reward_name"] = rewards_df["deals_used"].apply(extract_reward_name)

    markouts_df = sales_df[sales_df["deals_upper"].str.contains("MARK", na=False)].copy()

    days = max((sales_df["sale_date"].max() - sales_df["sale_date"].min()).days + 1, 1) if len(sales_df) > 0 else 1

    rewards_cost = float(rewards_df["cost"].sum())
    rewards_collected = float(rewards_df["actual_revenue"].sum())
    rewards_net = rewards_cost - rewards_collected

    markouts_cost = float(markouts_df["cost"].sum())
    markouts_collected = float(markouts_df["actual_revenue"].sum())
    markouts_net = markouts_cost - markouts_collected

    total_net = rewards_net + markouts_net
    monthly = total_net / days * 30

    summary = {
        "rewards_net_cost": round(rewards_net, 2),
        "markouts_net_cost": round(markouts_net, 2),
        "total_net_cost": round(total_net, 2),
        "monthly_projection": round(monthly, 2),
        "reward_redemptions": int(len(rewards_df)),
        "unique_reward_customers": int(rewards_df["customer_id"].nunique()) if len(rewards_df) > 0 else 0,
        "markout_transactions": int(len(markouts_df)),
        "employees_using_markouts": int(markouts_df["customer_name"].nunique()) if len(markouts_df) > 0 else 0,
    }

    # All rewards summary
    all_rewards = []
    if len(rewards_df) > 0:
        rsum = rewards_df.groupby("reward_name").agg(
            redemptions=("receipt_id", "count"),
            units=("quantity", "sum"),
            retail_value=("pre_discount_revenue", "sum"),
            cost=("cost", "sum"),
            collected=("actual_revenue", "sum"),
        ).reset_index()
        rsum["net_cost"] = rsum["cost"] - rsum["collected"]
        rsum["pct"] = (rsum["net_cost"] / rewards_net * 100).round(1) if rewards_net > 0 else 0
        rsum = rsum.sort_values("net_cost", ascending=False)
        all_rewards = rsum.fillna(0).to_dict("records")

    # Rewards by store
    rewards_by_store = {}
    if len(rewards_df) > 0:
        for s in sorted(rewards_df["store_clean"].dropna().unique()):
            sr = rewards_df[rewards_df["store_clean"] == s]
            ssum = sr.groupby("reward_name").agg(
                redemptions=("receipt_id", "count"),
                units=("quantity", "sum"),
                retail_value=("pre_discount_revenue", "sum"),
                cost=("cost", "sum"),
                collected=("actual_revenue", "sum"),
            ).reset_index()
            ssum["net_cost"] = ssum["cost"] - ssum["collected"]
            ssum = ssum.sort_values("net_cost", ascending=False)
            rewards_by_store[s] = ssum.fillna(0).to_dict("records")

    # Markouts by employee
    markouts_by_employee = []
    if len(markouts_df) > 0:
        emp_stores = markouts_df.groupby(["customer_name", "store_clean"]).size().reset_index(name="count")
        primary_store = emp_stores.loc[emp_stores.groupby("customer_name")["count"].idxmax()][["customer_name", "store_clean"]]

        emp_products = markouts_df.groupby("customer_name")["product"].apply(
            lambda x: ", ".join(x.unique()[:3]) + ("..." if len(x.unique()) > 3 else "")
        ).reset_index()
        emp_products.columns = ["customer_name", "products"]

        emp_sum = markouts_df.groupby("customer_name").agg(
            redemptions=("receipt_id", "count"),
            units=("quantity", "sum"),
            cost=("cost", "sum"),
        ).reset_index()
        emp_sum = emp_sum.merge(primary_store, on="customer_name", how="left")
        emp_sum = emp_sum.merge(emp_products, on="customer_name", how="left")
        emp_sum = emp_sum.sort_values("cost", ascending=False)
        emp_sum["rank"] = range(1, len(emp_sum) + 1)
        markouts_by_employee = emp_sum.fillna(0).to_dict("records")

    return {
        "date_range": date_range,
        "summary": summary,
        "all_rewards": all_rewards,
        "rewards_by_store": rewards_by_store,
        "markouts_by_employee": markouts_by_employee,
    }


def generate_excel(
    store: DataStore,
    output_path: str | Path,
    period: PeriodFilter | None = None,
) -> Path:
    data = generate_json(store, period)
    ew = ExcelWriter()
    s = data["summary"]
    dr = data["date_range"]

    # Executive Summary
    ws = ew.add_sheet("Executive Summary")
    ew.write_title(ws, "THRIVE CANNABIS", f"Rewards & Markout Report  |  {dr}")

    row = ew.write_section(ws, 4, "PROGRAM COSTS")
    row = ew.write_kpi_row(ws, row, [
        (s["rewards_net_cost"], "REWARDS NET COST", "currency"),
        (s["markouts_net_cost"], "MARKOUTS NET COST", "currency"),
        (s["total_net_cost"], "TOTAL NET COST", "currency"),
        (s["monthly_projection"], "MONTHLY PROJECTION", "currency"),
    ])

    row = ew.write_section(ws, row, "USAGE STATS")
    ew.write_kpi_row(ws, row, [
        (s["reward_redemptions"], "REWARD REDEMPTIONS", "number"),
        (s["unique_reward_customers"], "UNIQUE CUSTOMERS", "number"),
        (s["markout_transactions"], "MARKOUT TRANSACTIONS", "number"),
        (s["employees_using_markouts"], "EMPLOYEES USING", "number"),
    ])

    # All Rewards
    reward_cols = [
        ("reward_name", "text", "Reward Name"),
        ("redemptions", "number", "Redemptions"),
        ("units", "number", "Units"),
        ("retail_value", "currency", "Retail Value"),
        ("cost", "currency", "Product Cost"),
        ("net_cost", "currency", "Net Cost"),
        ("pct", "percent", "% of Total"),
    ]

    if data["all_rewards"]:
        ws2 = ew.add_sheet("All Rewards")
        ew.write_table(ws2, 1, reward_cols, data["all_rewards"],
                       highlight_fn=lambda i, r: "warning" if i < 3 else None)

        # By store
        store_cols = reward_cols[:6]  # without pct
        for store_name, rewards in data["rewards_by_store"].items():
            if not rewards:
                continue
            short = store_name.replace("Thrive ", "").replace("Cannabis ", "")[:12]
            ws_s = ew.add_sheet(f"Rewards - {short}")
            ws_s.cell(row=1, column=1).value = store_name
            ws_s.cell(row=1, column=1).font = SECTION_FONT
            total_net = sum(r.get("net_cost", 0) for r in rewards)
            ws_s.cell(row=2, column=1).value = f"Total Redemptions: {sum(r.get('redemptions', 0) for r in rewards)}  |  Net Cost: ${total_net:,.2f}"
            from app.excel.styles import SUBTITLE_FONT
            ws_s.cell(row=2, column=1).font = SUBTITLE_FONT
            ew.write_table(ws_s, 4, store_cols, rewards,
                           highlight_fn=lambda i, r: "warning" if i == 0 else None,
                           show_total=True)

    # Markouts by Employee
    if data["markouts_by_employee"]:
        ws_m = ew.add_sheet("Markouts by Employee")
        ew.write_table(ws_m, 1, [
            ("rank", "number", "Rank"),
            ("customer_name", "text", "Employee Name"),
            ("store_clean", "text", "Store"),
            ("redemptions", "number", "Redemptions"),
            ("units", "number", "Units"),
            ("cost", "currency", "Product Cost"),
            ("products", "text", "Products"),
        ], data["markouts_by_employee"],
           highlight_fn=lambda i, r: "orange" if i < 5 else None)

    return ew.save(output_path)
