"""
FastAPI dependencies — DataStore singleton, period parsing.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import Depends, HTTPException, Query

from app.data.store import DataStore
from app.data.schemas import PeriodFilter, PeriodType

# ---------------------------------------------------------------------------
# Global store singleton (set during startup)
# ---------------------------------------------------------------------------
_store: DataStore | None = None


def set_store(store: DataStore) -> None:
    global _store
    _store = store


def get_store() -> DataStore:
    if _store is None or not _store.is_loaded:
        raise HTTPException(503, "Data not loaded yet")
    return _store


def get_store_or_empty() -> DataStore:
    """Return the store even if it has no data (for upload/reload endpoints)."""
    if _store is None:
        raise HTTPException(503, "Server not initialized yet")
    return _store


# ---------------------------------------------------------------------------
# Period parsing from query params
# ---------------------------------------------------------------------------

def parse_period(
    period_type: Optional[str] = Query(None, description="month|quarter|year|custom|all"),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    quarter: Optional[int] = Query(None),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    store: Optional[str] = Query(None, description="Store name filter"),
) -> PeriodFilter | None:
    """Parse period query parameters into a PeriodFilter."""
    if period_type is None:
        if store:
            return PeriodFilter(PeriodType.ALL, store=store)
        return None

    try:
        pt = PeriodType(period_type)
    except ValueError:
        raise HTTPException(400, f"Invalid period_type: {period_type}")

    sd = dt.date.fromisoformat(start_date) if start_date else None
    ed = dt.date.fromisoformat(end_date) if end_date else None

    return PeriodFilter(
        period_type=pt,
        year=year,
        month=month,
        quarter=quarter,
        start_date=sd,
        end_date=ed,
        store=store,
    )


def parse_comparison_period(
    compare_period_type: Optional[str] = Query(None),
    compare_year: Optional[int] = Query(None),
    compare_month: Optional[int] = Query(None),
    compare_quarter: Optional[int] = Query(None),
    compare_start_date: Optional[str] = Query(None),
    compare_end_date: Optional[str] = Query(None),
) -> PeriodFilter | None:
    """Parse comparison period query parameters."""
    if compare_period_type is None:
        return None

    try:
        pt = PeriodType(compare_period_type)
    except ValueError:
        raise HTTPException(400, f"Invalid compare_period_type: {compare_period_type}")

    sd = dt.date.fromisoformat(compare_start_date) if compare_start_date else None
    ed = dt.date.fromisoformat(compare_end_date) if compare_end_date else None

    return PeriodFilter(
        period_type=pt,
        year=compare_year,
        month=compare_month,
        quarter=compare_quarter,
        start_date=sd,
        end_date=ed,
    )
