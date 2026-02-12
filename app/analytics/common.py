"""
Safe math helpers used across all analytics modules.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide safely, returning default if denominator is zero or NaN."""
    if denominator == 0 or pd.isna(denominator):
        return default
    result = numerator / denominator
    return default if pd.isna(result) else result


def calc_margin(revenue: float, cost: float) -> float:
    """Calculate margin percentage: (revenue - cost) / revenue * 100."""
    return safe_divide(revenue - cost, revenue) * 100


def calc_discount_rate(discounts: float, pre_discount_revenue: float) -> float:
    """Discount rate: discounts / pre_discount_revenue * 100."""
    return safe_divide(discounts, pre_discount_revenue) * 100


def pct_of_total(part: float, total: float) -> float:
    """Percentage of total."""
    return safe_divide(part, total) * 100


def pct_change(current: float, previous: float) -> float | None:
    """Percentage change from previous to current. Returns None if previous is 0."""
    if previous == 0 or pd.isna(previous):
        return None
    return (current - previous) / abs(previous) * 100


def safe_series_divide(
    numerator: pd.Series,
    denominator: pd.Series,
    default: float = 0.0,
) -> pd.Series:
    """Element-wise safe division for pandas Series."""
    return (numerator / denominator.replace(0, np.nan)).fillna(default)


def sanitize_for_json(obj):
    """Recursively convert numpy/pandas types to native Python for JSON serialization."""
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return 0.0 if np.isnan(obj) else float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return 0.0
    return obj
