"""
Thrive Analytics — FastAPI app factory with startup data loading.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.data.store import DataStore
from app.api.dependencies import set_store
from app.api.router_meta import router as meta_router
from app.api.router_brands import router as brands_router
from app.api.router_master import router as master_router
from app.api.router_reports import router as reports_router
from app.api.router_upload import router as upload_router
from app.api.router_dashboard import router as dashboard_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load all data at startup."""
    from app.config import INBOX_FOLDER, BRAND_REPORTS_FOLDER, REPORTS_FOLDER, SHARES_FOLDER
    for d in [INBOX_FOLDER, BRAND_REPORTS_FOLDER, REPORTS_FOLDER, SHARES_FOLDER]:
        d.mkdir(parents=True, exist_ok=True)

    # Diagnostic: show exactly where data lives
    import os
    print(f"  THRIVE_DATA_DIR = {os.environ.get('THRIVE_DATA_DIR', '(not set)')}")
    print(f"  INBOX_FOLDER = {INBOX_FOLDER}")
    print(f"  INBOX_FOLDER exists = {INBOX_FOLDER.exists()}")
    if INBOX_FOLDER.exists():
        all_csvs = list(INBOX_FOLDER.rglob("*.csv"))
        print(f"  CSV files found in inbox: {len(all_csvs)}")
        for f in all_csvs[:10]:
            print(f"    - {f.relative_to(INBOX_FOLDER)} ({f.stat().st_size:,} bytes)")

    store = DataStore()
    store.load()
    set_store(store)

    if store.row_count() > 0:
        print(f"\nThrive Analytics ready — {store.row_count():,} rows, "
              f"{len(store.stores())} stores, {len(store.brands())} brands\n")
    else:
        print("\nThrive Analytics ready — no data yet. Upload CSVs via Data Manager.\n")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Thrive Analytics API",
        description="Cannabis retail analytics — brand reports, master suite, shareable links",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(meta_router)
    app.include_router(brands_router)
    app.include_router(master_router)
    app.include_router(reports_router)
    app.include_router(upload_router)
    app.include_router(dashboard_router)

    # Serve dashboard at /
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
