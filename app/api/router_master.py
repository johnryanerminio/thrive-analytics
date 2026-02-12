"""
Master report endpoints — margin, deals, budtenders, customers, rewards + suite ZIP.
"""
from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.data.store import DataStore
from app.data.schemas import PeriodFilter
from app.api.dependencies import get_store, parse_period
from app.reports import margin_report, deal_report, budtender_report, customer_report, rewards_report
from app.config import REPORTS_FOLDER

router = APIRouter(prefix="/api/master", tags=["master"])


def _output_path(name: str) -> Path:
    REPORTS_FOLDER.mkdir(parents=True, exist_ok=True)
    return REPORTS_FOLDER / name


# ── Margin ─────────────────────────────────────────────────────────

@router.get("/margin")
def margin_json(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    return margin_report.generate_json(store, period)


@router.get("/margin/excel")
def margin_excel(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    path = margin_report.generate_excel(store, _output_path("Margin_Report.xlsx"), period)
    return FileResponse(path=str(path), filename=path.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Deals ──────────────────────────────────────────────────────────

@router.get("/deals")
def deals_json(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    return deal_report.generate_json(store, period)


@router.get("/deals/excel")
def deals_excel(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    path = deal_report.generate_excel(store, _output_path("Deal_Performance_Report.xlsx"), period)
    return FileResponse(path=str(path), filename=path.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Budtenders ─────────────────────────────────────────────────────

@router.get("/budtenders")
def budtenders_json(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    data = budtender_report.generate_json(store, period)
    if "error" in data:
        raise HTTPException(404, data["error"])
    return data


@router.get("/budtenders/excel")
def budtenders_excel(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    try:
        path = budtender_report.generate_excel(store, _output_path("Budtender_Performance_Report.xlsx"), period)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return FileResponse(path=str(path), filename=path.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Customers ──────────────────────────────────────────────────────

@router.get("/customers")
def customers_json(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    return customer_report.generate_json(store, period)


@router.get("/customers/excel")
def customers_excel(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    path = customer_report.generate_excel(store, _output_path("Customer_Insights_Report.xlsx"), period)
    return FileResponse(path=str(path), filename=path.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Rewards ────────────────────────────────────────────────────────

@router.get("/rewards")
def rewards_json(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    return rewards_report.generate_json(store, period)


@router.get("/rewards/excel")
def rewards_excel(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    path = rewards_report.generate_excel(store, _output_path("Rewards_Markout_Report.xlsx"), period)
    return FileResponse(path=str(path), filename=path.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Suite ZIP ──────────────────────────────────────────────────────

@router.get("/suite/excel")
def suite_zip(
    store: DataStore = Depends(get_store),
    period: PeriodFilter | None = Depends(parse_period),
):
    """Download all 5 master reports as a ZIP file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        path = margin_report.generate_excel(store, _output_path("Margin_Report.xlsx"), period)
        zf.write(path, path.name)

        path = deal_report.generate_excel(store, _output_path("Deal_Performance_Report.xlsx"), period)
        zf.write(path, path.name)

        try:
            path = budtender_report.generate_excel(store, _output_path("Budtender_Performance_Report.xlsx"), period)
            zf.write(path, path.name)
        except ValueError:
            pass  # No BT data — skip

        path = customer_report.generate_excel(store, _output_path("Customer_Insights_Report.xlsx"), period)
        zf.write(path, path.name)

        path = rewards_report.generate_excel(store, _output_path("Rewards_Markout_Report.xlsx"), period)
        zf.write(path, path.name)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=Thrive_Analytics_Suite.zip"},
    )
