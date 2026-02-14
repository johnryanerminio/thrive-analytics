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
def list_stores(store: DataStore = Depends(get_store_or_empty)):
    return StoresResponse(stores=store.stores() if not store.df.empty else [])


@router.get("/brands")
def list_brands(store: DataStore = Depends(get_store_or_empty)):
    from app.config import INTERNAL_BRANDS
    brands = store.brands() if not store.df.empty else []
    internal = [b for b in brands if b.upper() in INTERNAL_BRANDS]
    return {"brands": brands, "count": len(brands), "internal_brands": internal}


@router.get("/categories", response_model=CategoriesResponse)
def list_categories(store: DataStore = Depends(get_store_or_empty)):
    return CategoriesResponse(categories=store.categories() if not store.df.empty else [])


@router.get("/periods", response_model=PeriodsResponse)
def list_periods(store: DataStore = Depends(get_store_or_empty)):
    return PeriodsResponse(periods=store.periods_available() if not store.df.empty else [])


@router.post("/reload")
async def reload_data(store: DataStore = Depends(get_store_or_empty), background_tasks: BackgroundTasks = None):
    """Re-scan inbox and reload all data.

    Returns immediately, reload happens in background.
    """
    import threading

    def _do_reload():
        store.load()
        print(f"  Reload complete — {store.row_count():,} rows, {store.regular_count():,} regular")

    threading.Thread(target=_do_reload, daemon=True).start()
    return {
        "status": "reloading",
        "message": "Data reload started in background. Check /api/health for updated row counts.",
    }
