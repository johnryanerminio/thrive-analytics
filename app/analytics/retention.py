"""
Customer retention analytics — new/returning/churned, cohort retention, CLV.
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from app.analytics.common import safe_divide, sanitize_for_json


# A customer is "churned" if they haven't purchased in this many days
CHURN_THRESHOLD_DAYS = 90


def retention_summary(regular_df: pd.DataFrame) -> dict:
    """Full retention dashboard: monthly new/returning/churned, cohorts, CLV."""
    if regular_df.empty:
        return {"empty": True}

    df = regular_df[["customer_id", "actual_revenue", "completed_at", "year", "month"]].copy()
    df = df.dropna(subset=["customer_id"])
    df["ym"] = df["year"].astype(int) * 100 + df["month"].astype(int)

    # --- Monthly new vs returning customers ---
    cust_first = df.groupby("customer_id")["ym"].min().reset_index()
    cust_first.columns = ["customer_id", "first_ym"]
    df = df.merge(cust_first, on="customer_id", how="left")
    df["is_new"] = df["ym"] == df["first_ym"]

    monthly_cust = df.groupby("ym").agg(
        total_customers=("customer_id", "nunique"),
        total_revenue=("actual_revenue", "sum"),
    ).reset_index()

    new_cust = df[df["is_new"]].groupby("ym").agg(
        new_customers=("customer_id", "nunique"),
        new_revenue=("actual_revenue", "sum"),
    ).reset_index()

    returning_cust = df[~df["is_new"]].groupby("ym").agg(
        returning_customers=("customer_id", "nunique"),
        returning_revenue=("actual_revenue", "sum"),
    ).reset_index()

    monthly = monthly_cust.merge(new_cust, on="ym", how="left").merge(returning_cust, on="ym", how="left").fillna(0)
    monthly["year"] = monthly["ym"] // 100
    monthly["month"] = monthly["ym"] % 100
    monthly = monthly.sort_values("ym")

    monthly_list = []
    for _, r in monthly.iterrows():
        total = int(r["total_customers"])
        new = int(r["new_customers"])
        ret = int(r["returning_customers"])
        monthly_list.append({
            "year": int(r["year"]),
            "month": int(r["month"]),
            "label": f"{int(r['year'])}-{int(r['month']):02d}",
            "total_customers": total,
            "new_customers": new,
            "returning_customers": ret,
            "new_pct": round(safe_divide(new, total) * 100, 1),
            "returning_pct": round(safe_divide(ret, total) * 100, 1),
            "total_revenue": float(r["total_revenue"]),
            "new_revenue": float(r["new_revenue"]),
            "returning_revenue": float(r["returning_revenue"]),
        })

    # --- Churn analysis ---
    # For each month, count customers who were active in the prior 3 months
    # but NOT active in this month
    all_yms = sorted(monthly["ym"].unique())
    churn_list = []
    for i, ym in enumerate(all_yms):
        if i < 3:
            continue  # need 3 months of history
        prior_3 = set(all_yms[max(0, i - 3):i])
        current_customers = set(df[df["ym"] == ym]["customer_id"].unique())
        prior_customers = set(df[df["ym"].isin(prior_3)]["customer_id"].unique())
        churned = prior_customers - current_customers
        reactivated = current_customers & (
            set(df[(df["ym"] < all_yms[max(0, i - 3)]) & (~df["customer_id"].isin(prior_customers))]["customer_id"].unique())
            if i > 3 else set()
        )
        churn_rate = safe_divide(len(churned), len(prior_customers)) * 100
        churn_list.append({
            "label": f"{ym // 100}-{ym % 100:02d}",
            "year": ym // 100,
            "month": ym % 100,
            "active_prior_3m": len(prior_customers),
            "active_current": len(current_customers),
            "churned": len(churned),
            "churn_rate": round(churn_rate, 1),
            "retention_rate": round(100 - churn_rate, 1),
        })

    # --- Cohort retention ---
    # Group customers by their first purchase month, then track what % are still
    # active 1, 2, 3, ... months later
    cust_months = df.groupby("customer_id")["ym"].apply(set).reset_index()
    cust_months.columns = ["customer_id", "active_months"]
    cust_months = cust_months.merge(cust_first, on="customer_id", how="left")

    cohort_data = []
    cohort_yms = sorted(int(x) for x in cust_first["first_ym"].dropna().unique())
    for cohort_ym in cohort_yms:
        cohort_custs = cust_months[cust_months["first_ym"] == cohort_ym]
        cohort_size = len(cohort_custs)
        if cohort_size < 5:
            continue

        # Find index of cohort month in all_yms
        if cohort_ym not in all_yms:
            continue
        cohort_idx = all_yms.index(cohort_ym)

        retention_curve = []
        for offset in range(len(all_yms) - cohort_idx):
            target_ym = all_yms[cohort_idx + offset]
            active = sum(target_ym in ams for ams in cohort_custs["active_months"])
            retention_curve.append({
                "month_offset": offset,
                "active": active,
                "retention_pct": round(safe_divide(active, cohort_size) * 100, 1),
            })

        cohort_data.append({
            "cohort_label": f"{cohort_ym // 100}-{cohort_ym % 100:02d}",
            "cohort_size": cohort_size,
            "retention": retention_curve,
        })

    # Summarize cohort retention at key intervals (3m, 6m, 12m)
    cohort_summary = []
    for c in cohort_data:
        row = {
            "cohort": c["cohort_label"],
            "size": c["cohort_size"],
        }
        for target in [1, 3, 6, 12]:
            if target < len(c["retention"]):
                row[f"m{target}"] = c["retention"][target]["retention_pct"]
            else:
                row[f"m{target}"] = None
        cohort_summary.append(row)

    # --- Customer Lifetime Value ---
    cust_ltv = df.groupby("customer_id").agg(
        total_revenue=("actual_revenue", "sum"),
        first_purchase=("completed_at", "min"),
        last_purchase=("completed_at", "max"),
        transaction_months=("ym", "nunique"),
    ).reset_index()
    cust_ltv["tenure_days"] = (cust_ltv["last_purchase"] - cust_ltv["first_purchase"]).dt.days
    cust_ltv["monthly_value"] = cust_ltv["total_revenue"] / cust_ltv["transaction_months"].clip(lower=1)

    total_customers = len(cust_ltv)
    avg_ltv = float(cust_ltv["total_revenue"].mean())
    median_ltv = float(cust_ltv["total_revenue"].median())
    avg_tenure = float(cust_ltv["tenure_days"].mean())
    avg_monthly_value = float(cust_ltv["monthly_value"].mean())

    # LTV by tenure bucket
    cust_ltv["tenure_bucket"] = pd.cut(
        cust_ltv["tenure_days"],
        bins=[-1, 30, 90, 180, 365, 999999],
        labels=["< 1 month", "1-3 months", "3-6 months", "6-12 months", "12+ months"],
    )
    ltv_by_tenure = cust_ltv.groupby("tenure_bucket", observed=True).agg(
        customers=("customer_id", "count"),
        avg_revenue=("total_revenue", "mean"),
        total_revenue=("total_revenue", "sum"),
    ).reset_index()

    ltv_buckets = []
    for _, r in ltv_by_tenure.iterrows():
        ltv_buckets.append({
            "bucket": str(r["tenure_bucket"]),
            "customers": int(r["customers"]),
            "pct_of_total": round(safe_divide(int(r["customers"]), total_customers) * 100, 1),
            "avg_revenue": round(float(r["avg_revenue"]), 2),
            "total_revenue": float(r["total_revenue"]),
        })

    # --- Revenue at risk (from customers showing churn signals) ---
    # Customers who were active in the last 3 months of data but bought less
    # than half their usual monthly rate
    latest_ym = all_yms[-1] if all_yms else 0
    recent_3 = set(all_yms[-3:]) if len(all_yms) >= 3 else set(all_yms)
    recent_customers = df[df["ym"].isin(recent_3)].groupby("customer_id")["actual_revenue"].sum()
    at_risk_count = 0
    at_risk_revenue = 0.0
    if len(all_yms) > 6:
        prior_6 = set(all_yms[-9:-3]) if len(all_yms) >= 9 else set(all_yms[:-3])
        prior_avg = df[df["ym"].isin(prior_6)].groupby("customer_id")["actual_revenue"].mean()
        # Customers whose recent 3-month spend is less than 50% of their prior average
        for cid in recent_customers.index:
            if cid in prior_avg.index:
                if recent_customers[cid] < prior_avg[cid] * 0.5:
                    at_risk_count += 1
                    at_risk_revenue += float(prior_avg[cid])  # expected monthly spend

    # --- KPIs ---
    latest_month = monthly_list[-1] if monthly_list else {}
    kpis = {
        "total_unique_customers": total_customers,
        "avg_ltv": round(avg_ltv, 2),
        "median_ltv": round(median_ltv, 2),
        "avg_tenure_days": round(avg_tenure, 0),
        "avg_monthly_value": round(avg_monthly_value, 2),
        "latest_new_customers": latest_month.get("new_customers", 0),
        "latest_returning_customers": latest_month.get("returning_customers", 0),
        "latest_returning_pct": latest_month.get("returning_pct", 0),
        "latest_churn_rate": churn_list[-1]["churn_rate"] if churn_list else None,
        "at_risk_customers": at_risk_count,
        "at_risk_monthly_revenue": round(at_risk_revenue, 0),
    }

    return sanitize_for_json({
        "kpis": kpis,
        "monthly": monthly_list,
        "churn": churn_list,
        "cohort_summary": cohort_summary,
        "cohort_detail": cohort_data[:12],  # limit to 12 cohorts for payload size
        "ltv_buckets": ltv_buckets,
    })
