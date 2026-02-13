"""
Dashboard endpoints — Executive Summary, Month-over-Month, Store Performance, Year-End.
"""
from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.data.store import DataStore
from app.data.schemas import PeriodFilter
from app.api.dependencies import get_store, parse_period
from app.analytics.dashboard import (
    executive_summary,
    month_over_month,
    store_performance,
    year_end_summary,
)

router = APIRouter(prefix="/api", tags=["dashboard"])


def _clean(obj):
    """Recursively replace NaN/Inf floats with 0.0 for JSON safety."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return 0.0
    return obj


def _safe_json(data: dict) -> JSONResponse:
    return JSONResponse(content=_clean(data))


@router.get("/executive-summary")
def exec_summary(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    """Company-wide executive summary with KPIs, trends, and insights."""
    return _safe_json(executive_summary(store, period))


@router.get("/month-over-month")
def mom(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    """Monthly breakdown with MoM percentage changes."""
    return _safe_json(month_over_month(store, period))


@router.get("/store-performance")
def stores(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    """Store-level performance rankings and comparisons."""
    return _safe_json(store_performance(store, period))


@router.get("/year-end-summary")
def year_end(
    year: int = Query(..., description="Year to summarize (e.g. 2025)"),
    store: DataStore = Depends(get_store),
):
    """Annual summary report with highlights and YoY comparison."""
    return _safe_json(year_end_summary(store, year))
