"""
Heatmap analytics — traffic patterns by day-of-week and hour-of-day.

Produces company-wide and per-store heatmaps, peak-hour rankings,
daily summaries, and descriptive KPIs for the retail dashboard.
"""
from __future__ import annotations

import pandas as pd

from app.analytics.common import safe_divide, sanitize_for_json


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_MAX_STORES_FOR_DETAIL = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hour_label(hour: int) -> str:
    """Return human-readable hour like '1pm', '12am'."""
    if hour == 0:
        return "12am"
    if hour < 12:
        return f"{hour}am"
    if hour == 12:
        return "12pm"
    return f"{hour - 12}pm"


def _peak_description(df: pd.DataFrame) -> str:
    """Build a human-readable string like 'Saturday 1-3pm' from the top revenue band."""
    if df.empty:
        return "N/A"

    top = df.groupby(["day_of_week", "hour"], observed=True)["actual_revenue"].sum()
    if top.empty:
        return "N/A"

    best_day, best_hour = top.idxmax()
    day_name = _DAY_NAMES[best_day]

    # Extend window: find contiguous hours around the peak that are within 50%
    peak_val = top[(best_day, best_hour)]
    threshold = peak_val * 0.50
    day_hours = top.loc[best_day].sort_index()

    start, end = best_hour, best_hour
    for h in range(best_hour - 1, -1, -1):
        if h in day_hours.index and day_hours[h] >= threshold:
            start = h
        else:
            break
    for h in range(best_hour + 1, 24):
        if h in day_hours.index and day_hours[h] >= threshold:
            end = h
        else:
            break

    if start == end:
        return f"{day_name} {_hour_label(start)}"
    return f"{day_name} {_hour_label(start)}-{_hour_label(end)}"


# ---------------------------------------------------------------------------
# Company-wide heatmap grid
# ---------------------------------------------------------------------------

def _build_heatmap(df: pd.DataFrame) -> list[dict]:
    """Revenue + transaction count by (day_of_week, hour)."""
    grouped = (
        df.groupby(["day_of_week", "hour"], observed=True)
        .agg(
            revenue=("actual_revenue", "sum"),
            transactions=("receipt_id", "nunique"),
        )
        .reset_index()
    )

    rows: list[dict] = []
    for _, r in grouped.iterrows():
        day = int(r["day_of_week"])
        rows.append({
            "day": day,
            "day_name": _DAY_NAMES[day],
            "hour": int(r["hour"]),
            "revenue": round(float(r["revenue"]), 2),
            "transactions": int(r["transactions"]),
        })
    return rows


# ---------------------------------------------------------------------------
# Peak hours
# ---------------------------------------------------------------------------

def _peak_hours(df: pd.DataFrame) -> dict:
    """Top 5 hours by revenue and by transaction count."""
    grouped = (
        df.groupby(["day_of_week", "hour"], observed=True)
        .agg(
            revenue=("actual_revenue", "sum"),
            transactions=("receipt_id", "nunique"),
        )
        .reset_index()
    )

    top_rev = grouped.nlargest(5, "revenue")
    top_txn = grouped.nlargest(5, "transactions")

    peak_revenue = []
    for _, r in top_rev.iterrows():
        day = int(r["day_of_week"])
        peak_revenue.append({
            "day_name": _DAY_NAMES[day],
            "hour": int(r["hour"]),
            "hour_label": _hour_label(int(r["hour"])),
            "revenue": round(float(r["revenue"]), 2),
        })

    peak_transactions = []
    for _, r in top_txn.iterrows():
        day = int(r["day_of_week"])
        peak_transactions.append({
            "day_name": _DAY_NAMES[day],
            "hour": int(r["hour"]),
            "hour_label": _hour_label(int(r["hour"])),
            "transactions": int(r["transactions"]),
        })

    return {"peak_revenue": peak_revenue, "peak_transactions": peak_transactions}


# ---------------------------------------------------------------------------
# Daily summary
# ---------------------------------------------------------------------------

def _daily_summary(df: pd.DataFrame) -> list[dict]:
    """Revenue, transactions, avg basket per day of week."""
    grouped = (
        df.groupby("day_of_week", observed=True)
        .agg(
            revenue=("actual_revenue", "sum"),
            transactions=("receipt_id", "nunique"),
        )
        .reset_index()
        .sort_values("day_of_week")
    )

    rows: list[dict] = []
    for _, r in grouped.iterrows():
        day = int(r["day_of_week"])
        rev = float(r["revenue"])
        txn = int(r["transactions"])
        rows.append({
            "day_name": _DAY_NAMES[day],
            "revenue": round(rev, 2),
            "transactions": txn,
            "avg_basket": round(safe_divide(rev, txn), 2),
        })
    return rows


# ---------------------------------------------------------------------------
# Per-store heatmaps
# ---------------------------------------------------------------------------

def _store_heatmaps(df: pd.DataFrame) -> dict[str, list[dict]]:
    """Heatmap per store — only if fewer than _MAX_STORES_FOR_DETAIL stores."""
    stores = df["store_clean"].nunique()
    if stores == 0 or stores >= _MAX_STORES_FOR_DETAIL:
        return {}

    result: dict[str, list[dict]] = {}
    for store, sdf in df.groupby("store_clean", observed=True):
        grouped = (
            sdf.groupby(["day_of_week", "hour"], observed=True)
            .agg(
                revenue=("actual_revenue", "sum"),
                transactions=("receipt_id", "nunique"),
            )
            .reset_index()
        )
        rows: list[dict] = []
        for _, r in grouped.iterrows():
            rows.append({
                "day": int(r["day_of_week"]),
                "hour": int(r["hour"]),
                "revenue": round(float(r["revenue"]), 2),
                "transactions": int(r["transactions"]),
            })
        result[str(store)] = rows
    return result


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

def _kpis(df: pd.DataFrame) -> dict:
    """Busiest/quietest day, busiest hour, peak description."""
    daily = (
        df.groupby("day_of_week", observed=True)["actual_revenue"]
        .sum()
        .sort_values(ascending=False)
    )
    hourly = (
        df.groupby("hour", observed=True)["actual_revenue"]
        .sum()
        .sort_values(ascending=False)
    )

    busiest_day = _DAY_NAMES[int(daily.index[0])] if not daily.empty else "N/A"
    quietest_day = _DAY_NAMES[int(daily.index[-1])] if not daily.empty else "N/A"
    busiest_hour = int(hourly.index[0]) if not hourly.empty else 0

    return {
        "busiest_day": busiest_day,
        "busiest_hour": busiest_hour,
        "busiest_hour_label": _hour_label(busiest_hour),
        "quietest_day": quietest_day,
        "peak_description": _peak_description(df),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def traffic_heatmap(regular_df: pd.DataFrame) -> dict:
    """
    Build full traffic-heatmap payload from a REGULAR-transactions DataFrame.

    Parameters
    ----------
    regular_df : pd.DataFrame
        Must contain columns: completed_at, actual_revenue, quantity,
        receipt_id, store_clean.

    Returns
    -------
    dict with keys: kpis, heatmap, peak_hours, daily_summary, store_heatmaps
    """
    empty_result: dict = {
        "kpis": {
            "busiest_day": "N/A",
            "busiest_hour": 0,
            "busiest_hour_label": "12am",
            "quietest_day": "N/A",
            "peak_description": "N/A",
        },
        "heatmap": [],
        "peak_hours": {"peak_revenue": [], "peak_transactions": []},
        "daily_summary": [],
        "store_heatmaps": {},
    }

    if regular_df is None or regular_df.empty:
        return sanitize_for_json(empty_result)

    if "completed_at" not in regular_df.columns:
        return sanitize_for_json(empty_result)

    # Work on a copy to avoid mutating the caller's frame
    df = regular_df.copy()

    # Ensure completed_at is datetime
    df["completed_at"] = pd.to_datetime(df["completed_at"], errors="coerce")
    df = df.dropna(subset=["completed_at"])
    if df.empty:
        return sanitize_for_json(empty_result)

    # Extract time components (Monday=0 per ISO convention)
    df["day_of_week"] = df["completed_at"].dt.dayofweek
    df["hour"] = df["completed_at"].dt.hour

    result = {
        "kpis": _kpis(df),
        "heatmap": _build_heatmap(df),
        "peak_hours": _peak_hours(df),
        "daily_summary": _daily_summary(df),
        "store_heatmaps": _store_heatmaps(df),
    }

    return sanitize_for_json(result)
