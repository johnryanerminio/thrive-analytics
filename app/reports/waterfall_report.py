"""
Margin Waterfall report — decomposes margin change into root causes.
"""
from __future__ import annotations

from app.data.store import DataStore
from app.data.schemas import PeriodFilter
from app.analytics.waterfall import margin_waterfall
from app.analytics.common import sanitize_for_json


def generate_json(store: DataStore, period: PeriodFilter | None = None) -> dict:
    """Generate the margin waterfall JSON."""
    regular = store.get_regular(period)
    label = period.label if period else "All Time"

    if regular.empty:
        return sanitize_for_json({"period_label": label, "empty": True})

    data = margin_waterfall(regular, store, period)
    data["period_label"] = label
    return sanitize_for_json(data)
