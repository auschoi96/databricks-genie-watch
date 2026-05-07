"""Resources router: per-space configured + executed resources, workspace rollup."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query

from backend.models import ResourceRollupItem, ResourceUsage
from backend.routers._validators import validate_days, validate_space_id
from backend.services import genie_client, system_tables, uc_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _configured_resources(space_id: str) -> list[ResourceUsage]:
    try:
        space = genie_client.get_serialized_space(space_id)
    except Exception as e:
        logger.info("get_serialized_space(%s) failed: %s", space_id, e)
        return []
    ds = space.get("data_sources") or {}
    out: list[ResourceUsage] = []
    for t in ds.get("tables", []) or []:
        ident = t.get("identifier")
        if not ident:
            continue
        meta = uc_client.get_table(ident) or {}
        kind_raw = (meta.get("kind") or "").upper()
        kind = "view" if "VIEW" in kind_raw and "METRIC" not in kind_raw else "table"
        out.append(ResourceUsage(
            full_name=ident, kind=kind, source="configured",
            owner=meta.get("owner"), comment=meta.get("comment"),
        ))
    for mv in ds.get("metric_views", []) or []:
        ident = mv.get("identifier")
        if not ident:
            continue
        meta = uc_client.get_table(ident) or {}
        out.append(ResourceUsage(
            full_name=ident, kind="metric_view", source="configured",
            owner=meta.get("owner"), comment=meta.get("comment"),
        ))
    return out


def _executed_resources(space_id: str, days: int) -> list[ResourceUsage]:
    try:
        rows = system_tables.executed_resources(space_id, days=days)
    except Exception as e:
        logger.warning("executed_resources(%s) failed: %s", space_id, e)
        return []
    return [
        ResourceUsage(
            full_name=r["full_name"],
            kind="table",
            source="executed",
            query_count=int(r.get("query_count") or 0),
            last_used=r.get("last_used"),
        )
        for r in rows
        if r.get("full_name")
    ]


@router.get("/spaces/{space_id}/resources")
async def get_space_resources(
    space_id: str,
    days: int = Query(30, ge=1, le=365),
) -> list[dict]:
    sid = validate_space_id(space_id)
    days = validate_days(days, default=30)
    # Run the Genie API fetch + UC enrichment AND the lineage SQL in parallel.
    configured, executed = await asyncio.gather(
        asyncio.to_thread(_configured_resources, sid),
        asyncio.to_thread(_executed_resources, sid, days),
    )
    by_name: dict[str, ResourceUsage] = {r.full_name: r for r in configured}
    for r in executed:
        if r.full_name in by_name:
            existing = by_name[r.full_name]
            existing.source = "both"
            existing.query_count = r.query_count
            existing.last_used = r.last_used
        else:
            by_name[r.full_name] = r
    items = sorted(
        by_name.values(),
        key=lambda x: (-(x.query_count or 0), x.full_name),
    )
    return [r.model_dump(mode="json") for r in items]


@router.get("/resources/rollup")
async def resource_rollup(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    days = validate_days(days, default=30)
    try:
        rows = system_tables.resource_rollup(days=days, limit=limit)
    except Exception as e:
        logger.warning("resource_rollup failed: %s", e)
        return []
    return [
        ResourceRollupItem(
            full_name=r["full_name"],
            space_count=int(r.get("space_count") or 0),
            query_count_total=int(r.get("query_count_total") or 0),
            last_used=r.get("last_used"),
        ).model_dump(mode="json")
        for r in rows
        if r.get("full_name")
    ]


@router.get("/resources/spaces")
async def spaces_using_resource(
    full_name: str,
    days: int = Query(30, ge=1, le=365),
) -> list[str]:
    days = validate_days(days, default=30)
    try:
        return system_tables.spaces_using_resource(full_name, days=days)
    except Exception as e:
        logger.warning("spaces_using_resource failed: %s", e)
        return []
