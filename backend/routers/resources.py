"""Resources router: per-space configured + executed resources, workspace rollup."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Query

from backend.models import (
    ResourceGraph,
    ResourceGraphEdge,
    ResourceGraphSpaceNode,
    ResourceRollupItem,
    ResourceUsage,
)
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


@router.get("/resources/graph")
async def resource_graph(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(2000, ge=10, le=10000),
) -> dict:
    """Bipartite graph of Genie Spaces ↔ Resources (executed lineage).

    Returns up to `limit` edges sorted by query_count. `spaces` enriches each
    referenced space_id with a title (from the Genie Space cache) when known
    so the graph can show human-readable labels instead of opaque IDs.
    """
    days = validate_days(days, default=30)
    try:
        rows = await asyncio.to_thread(system_tables.resource_graph_edges, days, limit)
    except Exception as e:
        logger.warning("resource_graph failed: %s", e)
        rows = []

    edges = [
        ResourceGraphEdge(
            space_id=r["space_id"],
            full_name=r["full_name"],
            query_count=int(r.get("query_count") or 0),
            last_used=r.get("last_used"),
        )
        for r in rows
        if r.get("space_id") and r.get("full_name")
    ]

    referenced = {e.space_id for e in edges}
    space_titles: dict[str, Optional[str]] = {sid: None for sid in referenced}
    try:
        for sp in genie_client.list_genie_spaces():
            sid = sp.get("space_id") or sp.get("id")
            if sid in referenced:
                space_titles[sid] = sp.get("title")
    except Exception as e:  # noqa: BLE001 — title lookup is best-effort
        logger.info("list_genie_spaces failed for graph titles: %s", e)

    spaces = [
        ResourceGraphSpaceNode(space_id=sid, title=title)
        for sid, title in sorted(space_titles.items())
    ]
    return ResourceGraph(
        edges=edges,
        spaces=spaces,
        days=days,
        truncated=len(rows) >= limit,
    ).model_dump(mode="json")
