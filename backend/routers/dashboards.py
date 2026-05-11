"""Dashboard embed-config router.

Mints scoped embed tokens so the frontend AI/BI SDK can render a
published Lakeview dashboard without depending on the viewer having
an active workspace session (which the cross-origin iframe approach
needs and which third-party-cookie policies increasingly block).
"""

from __future__ import annotations

import logging
import os
import re

from fastapi import APIRouter, HTTPException, Request

from backend.services.auth import get_databricks_host
from backend.services.embed_tokens import mint_embed_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboards")

_DASHBOARD_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def _allowed_dashboard_ids() -> set[str]:
    """IDs the app is willing to mint embed tokens for.

    Restricted to dashboards configured at deploy time. We don't accept
    arbitrary IDs from the client; otherwise this endpoint would be a
    generic token-minting service for the workspace's SP.
    """
    ids: set[str] = set()
    cost_id = os.environ.get("DASHBOARD_COST_ID")
    if cost_id:
        ids.add(cost_id)
    return ids


@router.get("/{dashboard_id}/embed-config")
async def get_embed_config(dashboard_id: str, request: Request) -> dict:
    """Return the config the AI/BI SDK needs to render the dashboard.

    The SDK calls this on mount and again whenever the token nears
    expiry (via its getNewToken callback).
    """
    if not _DASHBOARD_ID_RE.match(dashboard_id):
        raise HTTPException(status_code=400, detail="dashboard_id must be a 32-char hex string")

    if dashboard_id not in _allowed_dashboard_ids():
        raise HTTPException(
            status_code=403,
            detail="dashboard_id is not configured for embedding in this app",
        )

    workspace_id = os.environ.get("DATABRICKS_WORKSPACE_ID")
    workspace_url = get_databricks_host()
    if not workspace_id or not workspace_url:
        raise HTTPException(
            status_code=500,
            detail="DATABRICKS_WORKSPACE_ID / DATABRICKS_HOST not available",
        )

    viewer = request.headers.get("X-Forwarded-User") or request.headers.get("X-Forwarded-Email")

    try:
        token = await mint_embed_token(dashboard_id, external_viewer_id=viewer)
    except Exception as e:
        logger.exception("embed-token mint failed for dashboard %s", dashboard_id)
        raise HTTPException(status_code=502, detail=f"embed-token mint failed: {e}")

    return {
        "workspace_url": workspace_url,
        "workspace_id": workspace_id,
        "dashboard_id": dashboard_id,
        "embed_token": token.access_token,
        "expires_in": token.expires_in,
    }
