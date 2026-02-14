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


def fillna_numeric(df: pd.DataFrame, value=0) -> pd.DataFrame:
    """Fill NaN with value for numeric columns only.

    Safe to use when df contains categorical columns — avoids
    TypeError from pandas when calling df.fillna(0) with mixed dtypes.
    """
    num_cols = df.select_dtypes(include="number").columns
    if len(num_cols):
        df = df.copy()
        df[num_cols] = df[num_cols].fillna(value)
    return df


def safe_series_divide(
    numerator: pd.Series,
    denominator: pd.Series,
    default: float = 0.0,
) -> pd.Series:
    """Element-wise safe division for pandas Series."""
    return (numerator / denominator.replace(0, np.nan)).fillna(default)


def sanitize_for_json(obj):
    """Recursively convert numpy/pandas types to native Python for JSON serialization."""
    import math
    if isinstance(obj, dict):
        clean = {}
        for k, v in obj.items():
            # Sanitize keys: skip NaN/None keys, convert non-string keys to str
            if k is None:
                continue
            if isinstance(k, float) and (math.isnan(k) or math.isinf(k)):
                continue
            try:
                if isinstance(k, (np.floating,)) and (math.isnan(float(k)) or math.isinf(float(k))):
                    continue
            except (TypeError, ValueError):
                pass
            clean[str(k) if not isinstance(k, str) else k] = sanitize_for_json(v)
        return clean
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return 0.0 if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return sanitize_for_json(obj.tolist())
    if isinstance(obj, float):
        return 0.0 if (math.isnan(obj) or math.isinf(obj)) else obj
    if pd.api.types.is_scalar(obj) and pd.isna(obj):
        return None
    return obj
