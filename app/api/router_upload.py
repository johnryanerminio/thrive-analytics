"""
Upload endpoints: upload, list, delete CSV files.
Reload lives in router_meta.py.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File

from app.config import INBOX_FOLDER

router = APIRouter(prefix="/api", tags=["upload"])


def _resolve_year_folder(filename: str) -> Path:
    """Determine which year subfolder to save a CSV into based on filename dates."""
    m = re.search(r"(\d{4})-\d{2}-\d{2}", filename)
    year = m.group(1) if m else str(datetime.now().year)
    return INBOX_FOLDER / year


@router.post("/upload")
async def upload_csvs(files: list[UploadFile] = File(...)):
    """Upload one or more CSV files to the inbox."""
    saved = []
    for f in files:
        if not f.filename or not f.filename.lower().endswith(".csv"):
            raise HTTPException(400, f"Only .csv files are accepted (got '{f.filename}')")

        dest_dir = _resolve_year_folder(f.filename)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f.filename

        content = await f.read()
        dest.write_bytes(content)
        saved.append({"name": f.filename, "path": str(dest.relative_to(INBOX_FOLDER)), "size": len(content)})

    return {"status": "uploaded", "count": len(saved), "files": saved}


@router.get("/upload/files")
def list_files():
    """List all CSV files in the inbox with sizes."""
    files = []
    if INBOX_FOLDER.exists():
        for csv_file in sorted(INBOX_FOLDER.rglob("*.csv")):
            stat = csv_file.stat()
            files.append({
                "name": csv_file.name,
                "path": str(csv_file.relative_to(INBOX_FOLDER)),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
    return {"files": files, "count": len(files)}


@router.delete("/upload/{filename:path}")
def delete_file(filename: str):
    """Delete a specific CSV file from the inbox."""
    target = (INBOX_FOLDER / filename).resolve()
    # Ensure the target is actually inside INBOX_FOLDER
    if not str(target).startswith(str(INBOX_FOLDER.resolve())):
        raise HTTPException(400, "Invalid file path")
    if not target.exists():
        raise HTTPException(404, f"File not found: {filename}")
    target.unlink()
    return {"status": "deleted", "file": filename}
