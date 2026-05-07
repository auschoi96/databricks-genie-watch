"""Settings router: eval mapping CRUD, conversation cache refresh, health."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from backend.models import (
    EvalExperimentMapping,
    HealthStatus,
    SetEvalMappingRequest,
)
from backend.routers._validators import validate_space_id
from backend.services import conversations_client, genie_client, lakebase, mlflow_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings")


@router.get("/health")
async def health() -> dict:
    return HealthStatus(
        lakebase_available=lakebase.is_available(),
        obo_active=False,  # filled in by middleware-aware caller; keep simple
        warehouse_id=os.environ.get("SQL_WAREHOUSE_ID"),
        dashboard_cost_id=os.environ.get("DASHBOARD_COST_ID") or None,
    ).model_dump(mode="json")


@router.get("/eval-mapping/{space_id}")
async def get_mapping(space_id: str) -> dict:
    sid = validate_space_id(space_id)
    m = await lakebase.get_eval_mapping(sid)
    if not m:
        return {}
    return EvalExperimentMapping(**m).model_dump(mode="json")


@router.post("/eval-mapping/{space_id}")
async def set_mapping(space_id: str, body: SetEvalMappingRequest, request: Request) -> dict:
    sid = validate_space_id(space_id)
    exp = mlflow_client.get_experiment(body.experiment_id)
    if exp is None:
        raise HTTPException(
            status_code=400,
            detail=f"experiment_id {body.experiment_id!r} not found or not readable",
        )
    user = request.headers.get("X-Forwarded-User") or os.environ.get("DEV_USER_EMAIL", "unknown")
    record = await lakebase.upsert_eval_mapping(
        space_id=sid, experiment_id=body.experiment_id, created_by=user,
    )
    return EvalExperimentMapping(**record).model_dump(mode="json")


@router.delete("/eval-mapping/{space_id}")
async def delete_mapping(space_id: str) -> dict:
    sid = validate_space_id(space_id)
    await lakebase.delete_eval_mapping(sid)
    return {"deleted": sid}


@router.post("/cache/refresh")
async def refresh_cache(background_tasks: BackgroundTasks) -> dict:
    """Refresh the conversation/message cache for every visible space.

    Runs in the background — the request returns immediately so the UI doesn't
    hang waiting on what could be O(spaces × pages × pages).
    """
    try:
        spaces = genie_client.list_genie_spaces()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"could not list spaces: {e}")
    for s in spaces:
        sid = s.get("id")
        if not sid:
            continue
        background_tasks.add_task(_safe_sync, sid)
    return {"queued": len(spaces)}


async def _safe_sync(space_id: str) -> None:
    try:
        await conversations_client.sync_space(space_id, fetch_messages=True)
    except Exception as e:
        logger.warning("sync_space(%s) failed: %s", space_id, e)
