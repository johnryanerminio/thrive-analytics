"""
Shareable report endpoints — create + retrieve.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException

from app.data.store import DataStore
from app.data.schemas import PeriodFilter, PeriodType
from app.api.dependencies import get_store
from app.api.response_models import ShareCreateRequest, ShareResponse
from app.api.share import create_share, get_share
from app.reports import brand_dispensary, brand_facing, margin_report, deal_report
from app.reports import budtender_report, customer_report, rewards_report

router = APIRouter(prefix="/api/reports", tags=["sharing"])


def _build_period(req: ShareCreateRequest) -> PeriodFilter | None:
    if req.period_type is None:
        return None
    sd = dt.date.fromisoformat(req.start_date) if req.start_date else None
    ed = dt.date.fromisoformat(req.end_date) if req.end_date else None
    return PeriodFilter(
        period_type=PeriodType(req.period_type),
        year=req.year,
        month=req.month,
        quarter=req.quarter,
        start_date=sd,
        end_date=ed,
        store=req.store,
    )


_GENERATORS = {
    "brand_dispensary": lambda store, req, period: brand_dispensary.generate_json(store, req.brand, period),
    "brand_facing": lambda store, req, period: brand_facing.generate_json(store, req.brand, period),
    "margin": lambda store, req, period: margin_report.generate_json(store, period),
    "deals": lambda store, req, period: deal_report.generate_json(store, period),
    "budtenders": lambda store, req, period: budtender_report.generate_json(store, period),
    "customers": lambda store, req, period: customer_report.generate_json(store, period),
    "rewards": lambda store, req, period: rewards_report.generate_json(store, period),
}


@router.post("/share", response_model=ShareResponse)
def create_shared_report(
    req: ShareCreateRequest,
    store: DataStore = Depends(get_store),
):
    """Create a shareable link by freezing report data to a JSON snapshot."""
    gen = _GENERATORS.get(req.report_type)
    if gen is None:
        raise HTTPException(400, f"Unknown report_type: {req.report_type}. Valid: {list(_GENERATORS.keys())}")

    if req.report_type in ("brand_dispensary", "brand_facing") and not req.brand:
        raise HTTPException(400, "brand is required for brand reports")

    period = _build_period(req)
    data = gen(store, req, period)

    if isinstance(data, dict) and "error" in data:
        raise HTTPException(404, data["error"])

    share = create_share(data, req.report_type)
    return ShareResponse(**share)


@router.get("/share/{share_id}")
def get_shared_report(share_id: str):
    """Retrieve a previously shared report."""
    payload = get_share(share_id)
    if payload is None:
        raise HTTPException(404, "Share not found or expired")
    return payload["data"]
