"""
Revenue forecasting with seasonality adjustment.

Produces a 3-month forward projection based on trailing averages and
year-over-year seasonal patterns.
"""
from __future__ import annotations

import calendar
from typing import Any

import numpy as np
import pandas as pd

from app.analytics.common import safe_divide, sanitize_for_json


def revenue_forecast(regular_df: pd.DataFrame) -> dict[str, Any]:
    """Build a revenue/profit forecast from regular transaction data.

    Parameters
    ----------
    regular_df : pd.DataFrame
        Filtered to regular (non-reward/markout) transactions.  Expected
        columns: ``actual_revenue``, ``net_profit``, ``year``, ``month``,
        ``completed_at``.

    Returns
    -------
    dict with keys ``historical``, ``forecast``, ``growth_rate``,
    ``trajectory``, ``seasonal_pattern``.
    """
    empty_result: dict[str, Any] = {
        "historical": [],
        "forecast": [],
        "growth_rate": None,
        "trajectory": "stable",
        "seasonal_pattern": [],
    }

    if regular_df is None or regular_df.empty:
        return sanitize_for_json(empty_result)

    # ------------------------------------------------------------------
    # 1. Monthly aggregation
    # ------------------------------------------------------------------
    monthly = (
        regular_df
        .groupby(["year", "month"], as_index=False)
        .agg(revenue=("actual_revenue", "sum"), profit=("net_profit", "sum"))
        .sort_values(["year", "month"])
        .reset_index(drop=True)
    )

    if monthly.empty:
        return sanitize_for_json(empty_result)

    # ------------------------------------------------------------------
    # 2. Trailing 3-month averages
    # ------------------------------------------------------------------
    monthly["trailing_3m_revenue"] = (
        monthly["revenue"].rolling(window=3, min_periods=1).mean()
    )
    monthly["trailing_3m_profit"] = (
        monthly["profit"].rolling(window=3, min_periods=1).mean()
    )

    # ------------------------------------------------------------------
    # 3. Build historical list
    # ------------------------------------------------------------------
    historical: list[dict] = []
    for _, row in monthly.iterrows():
        yr, mo = int(row["year"]), int(row["month"])
        historical.append({
            "year": yr,
            "month": mo,
            "label": f"{calendar.month_abbr[mo]} {yr}",
            "revenue": round(float(row["revenue"]), 2),
            "profit": round(float(row["profit"]), 2),
            "trailing_3m_revenue": round(float(row["trailing_3m_revenue"]), 2),
            "trailing_3m_profit": round(float(row["trailing_3m_profit"]), 2),
        })

    # ------------------------------------------------------------------
    # 4. Growth rate & trajectory
    # ------------------------------------------------------------------
    n = len(monthly)
    if n >= 6:
        current_3m = monthly["revenue"].iloc[-3:].mean()
        prior_3m = monthly["revenue"].iloc[-6:-3].mean()
        growth_rate = safe_divide(current_3m - prior_3m, abs(prior_3m)) * 100
    elif n >= 3:
        current_3m = monthly["revenue"].iloc[-3:].mean()
        prior_3m = monthly["revenue"].iloc[: max(n - 3, 1)].mean()
        growth_rate = safe_divide(current_3m - prior_3m, abs(prior_3m)) * 100
    else:
        current_3m = monthly["revenue"].mean()
        growth_rate = None

    if growth_rate is None:
        trajectory = "stable"
    elif growth_rate > 2.0:
        trajectory = "accelerating"
    elif growth_rate < -2.0:
        trajectory = "decelerating"
    else:
        trajectory = "stable"

    # ------------------------------------------------------------------
    # 5. Seasonal pattern (year-over-year factors)
    # ------------------------------------------------------------------
    # Use the most recent complete year for the baseline.  If no full year
    # exists, use all available data.
    yearly_totals = monthly.groupby("year")["revenue"].agg(["sum", "count"])
    complete_years = yearly_totals[yearly_totals["count"] == 12].index.tolist()

    if complete_years:
        base_year = max(complete_years)
        base_data = monthly[monthly["year"] == base_year]
    else:
        base_data = monthly

    base_avg = safe_divide(base_data["revenue"].sum(), len(base_data))
    month_factors: dict[int, float] = {}
    for mo in range(1, 13):
        mo_rows = base_data[base_data["month"] == mo]
        if mo_rows.empty or base_avg == 0:
            month_factors[mo] = 1.0
        else:
            month_factors[mo] = round(float(mo_rows["revenue"].sum() / base_avg), 4)

    seasonal_pattern = [
        {"month_name": calendar.month_name[m], "factor": month_factors[m]}
        for m in range(1, 13)
    ]

    # ------------------------------------------------------------------
    # 6. Forecast (3 months forward) — requires >= 6 months of history
    # ------------------------------------------------------------------
    forecast: list[dict] = []
    if n >= 6:
        trailing_rev = float(monthly["revenue"].iloc[-3:].mean())
        trailing_prof = float(monthly["profit"].iloc[-3:].mean())

        last_year = int(monthly["year"].iloc[-1])
        last_month = int(monthly["month"].iloc[-1])

        for i in range(1, 4):
            fwd_month = (last_month + i - 1) % 12 + 1
            fwd_year = last_year + (last_month + i - 1) // 12

            # Seasonality: use same-month from prior year if available
            prior_rows = monthly[
                (monthly["year"] == fwd_year - 1) & (monthly["month"] == fwd_month)
            ]
            if not prior_rows.empty:
                prior_year_data = monthly[monthly["year"] == fwd_year - 1]
                prior_year_avg = safe_divide(
                    prior_year_data["revenue"].sum(), len(prior_year_data)
                )
                if prior_year_avg > 0:
                    factor = float(prior_rows["revenue"].iloc[0]) / prior_year_avg
                else:
                    factor = 1.0
            else:
                factor = month_factors.get(fwd_month, 1.0)

            proj_rev = round(trailing_rev * factor, 2)
            proj_prof = round(trailing_prof * factor, 2)

            forecast.append({
                "year": fwd_year,
                "month": fwd_month,
                "label": f"{calendar.month_abbr[fwd_month]} {fwd_year}",
                "projected_revenue": proj_rev,
                "projected_profit": proj_prof,
                "seasonality_factor": round(factor, 4),
            })

    result: dict[str, Any] = {
        "historical": historical,
        "forecast": forecast,
        "growth_rate": round(growth_rate, 2) if growth_rate is not None else None,
        "trajectory": trajectory,
        "seasonal_pattern": seasonal_pattern,
    }
    return sanitize_for_json(result)
