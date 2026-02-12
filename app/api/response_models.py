"""
Pydantic response schemas for the API.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    rows: int
    regular_rows: int
    stores: int
    brands: int
    periods: int


class StoresResponse(BaseModel):
    stores: list[str]


class BrandsResponse(BaseModel):
    brands: list[str]
    count: int


class CategoriesResponse(BaseModel):
    categories: list[str]


class PeriodsResponse(BaseModel):
    periods: list[dict]


class ReportResponse(BaseModel):
    """Generic wrapper for any JSON report."""
    data: dict[str, Any]


class ShareCreateRequest(BaseModel):
    report_type: str  # "brand_dispensary", "brand_facing", "margin", etc.
    brand: Optional[str] = None
    period_type: Optional[str] = None
    year: Optional[int] = None
    month: Optional[int] = None
    quarter: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    store: Optional[str] = None


class ShareResponse(BaseModel):
    id: str
    url: str
    expires_at: str
    report_type: str
