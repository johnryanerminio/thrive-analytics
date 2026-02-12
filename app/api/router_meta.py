"""
Meta endpoints: health, stores, brands, categories, periods, reload.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.data.store import DataStore
from app.api.dependencies import get_store, get_store_or_empty, set_store
from app.api.response_models import (
    HealthResponse, StoresResponse, BrandsResponse, CategoriesResponse, PeriodsResponse,
)

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health", response_model=HealthResponse)
def health(store: DataStore = Depends(get_store_or_empty)):
    return HealthResponse(
        status="ok",
        rows=store.row_count(),
        regular_rows=store.regular_count(),
        stores=len(store.stores()) if not store.df.empty else 0,
        brands=len(store.brands()) if not store.df.empty else 0,
        periods=len(store.periods_available()),
    )


@router.get("/stores", response_model=StoresResponse)
def list_stores(store: DataStore = Depends(get_store)):
    return StoresResponse(stores=store.stores())


@router.get("/brands", response_model=BrandsResponse)
def list_brands(store: DataStore = Depends(get_store)):
    brands = store.brands()
    return BrandsResponse(brands=brands, count=len(brands))


@router.get("/categories", response_model=CategoriesResponse)
def list_categories(store: DataStore = Depends(get_store)):
    return CategoriesResponse(categories=store.categories())


@router.get("/periods", response_model=PeriodsResponse)
def list_periods(store: DataStore = Depends(get_store)):
    return PeriodsResponse(periods=store.periods_available())


@router.post("/reload")
def reload_data(store: DataStore = Depends(get_store_or_empty)):
    """Re-scan inbox and reload all data."""
    store.load()
    return {
        "status": "reloaded",
        "rows": store.row_count(),
        "regular_rows": store.regular_count(),
    }
