"""
Brand report endpoints — dispensary + brand-facing, JSON + Excel.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from app.data.store import DataStore
from app.data.schemas import PeriodFilter
from app.api.dependencies import get_store, parse_period, parse_comparison_period
from app.reports import brand_dispensary, brand_facing
from app.config import BRAND_REPORTS_FOLDER
from app.analytics.common import sanitize_for_json

router = APIRouter(prefix="/api/brands", tags=["brands"])


def _safe_json(data: dict) -> JSONResponse:
    return JSONResponse(content=sanitize_for_json(data))


@router.get("/{brand}/report")
def brand_report_json(
    brand: str,
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
    comparison: PeriodFilter | None = Depends(parse_comparison_period),
):
    """Dispensary-side brand report as JSON."""
    data = brand_dispensary.generate_json(store, brand, period, comparison)
    if "error" in data:
        raise HTTPException(404, data["error"])
    return _safe_json(data)


@router.get("/{brand}/report/excel")
def brand_report_excel(
    brand: str,
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
    comparison: PeriodFilter | None = Depends(parse_comparison_period),
):
    """Dispensary-side brand report as Excel download."""
    safe = brand.replace("/", "-").replace("\\", "-")[:40]
    out_path = BRAND_REPORTS_FOLDER / f"Brand_Report_{safe}.xlsx"
    try:
        brand_dispensary.generate_excel(store, brand, out_path, period, comparison)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return FileResponse(
        path=str(out_path),
        filename=out_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/{brand}/facing")
def brand_facing_json(
    brand: str,
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    """Brand-facing inverse report as JSON."""
    data = brand_facing.generate_json(store, brand, period)
    if "error" in data:
        raise HTTPException(404, data["error"])
    return _safe_json(data)


@router.get("/{brand}/facing/excel")
def brand_facing_excel(
    brand: str,
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    """Brand-facing inverse report as Excel download."""
    safe = brand.replace("/", "-").replace("\\", "-")[:40]
    out_path = BRAND_REPORTS_FOLDER / f"Brand_Facing_{safe}.xlsx"
    try:
        brand_facing.generate_excel(store, brand, out_path, period)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return FileResponse(
        path=str(out_path),
        filename=out_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/{brand}/trend")
def brand_trend(
    brand: str,
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    """Monthly trend data for a brand."""
    from app.analytics.velocity import monthly_trend
    brand_df = store.get_brand(brand, period)
    if brand_df.empty:
        raise HTTPException(404, f"No data for brand '{brand}'")
    return {"brand": brand, "trend": monthly_trend(brand_df)}


@router.get("/{brand}/velocity")
def brand_velocity(
    brand: str,
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    """Velocity metrics for a brand."""
    from app.analytics.velocity import velocity_metrics, velocity_by_category
    brand_df = store.get_brand(brand, period)
    regular_df = store.get_regular(period)
    if brand_df.empty:
        raise HTTPException(404, f"No data for brand '{brand}'")
    return {
        "brand": brand,
        "velocity": velocity_metrics(brand_df, regular_df),
        "by_category": velocity_by_category(brand_df, regular_df),
    }
