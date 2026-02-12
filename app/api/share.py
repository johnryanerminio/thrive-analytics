"""
Shareable link generation — JSON snapshots with unique IDs.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from app.config import SHARES_FOLDER, SHARE_EXPIRY_DAYS


def create_share(report_data: dict, report_type: str) -> dict:
    """Freeze report data to a JSON file with a unique ID."""
    share_id = uuid.uuid4().hex[:12]
    expires_at = datetime.now() + timedelta(days=SHARE_EXPIRY_DAYS)

    SHARES_FOLDER.mkdir(parents=True, exist_ok=True)
    share_path = SHARES_FOLDER / f"{share_id}.json"

    payload = {
        "id": share_id,
        "report_type": report_type,
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at.isoformat(),
        "data": report_data,
    }

    share_path.write_text(json.dumps(payload, default=str))

    return {
        "id": share_id,
        "url": f"/api/reports/share/{share_id}",
        "expires_at": expires_at.isoformat(),
        "report_type": report_type,
    }


def get_share(share_id: str) -> dict | None:
    """Retrieve a shared report by ID."""
    share_path = SHARES_FOLDER / f"{share_id}.json"
    if not share_path.exists():
        return None

    payload = json.loads(share_path.read_text())

    # Check expiry
    expires = datetime.fromisoformat(payload["expires_at"])
    if datetime.now() > expires:
        share_path.unlink(missing_ok=True)
        return None

    return payload
