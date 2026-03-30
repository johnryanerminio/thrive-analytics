"""
Product Intelligence report — ABC classification, dead stock, velocity trends.
"""
from __future__ import annotations

from app.data.store import DataStore
from app.data.schemas import PeriodFilter
from app.analytics.product_intel import product_intelligence
from app.analytics.common import sanitize_for_json


def generate_json(store: DataStore, period: PeriodFilter | None = None) -> dict:
    """Generate the product intelligence JSON."""
    regular = store.get_regular(period)
    label = period.label if period else "All Time"

    if regular.empty:
        return sanitize_for_json({"period_label": label, "empty": True})

    data = product_intelligence(regular)
    data["period_label"] = label
    data["date_range"] = store.date_range(period)
    return sanitize_for_json(data)
