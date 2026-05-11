"""Feedback rollup router.

Exposes a single workspace-wide aggregate over system.access.audit, used by
the Feedback page. Per-space drill-down lives under /api/spaces/{id}/feedback
(see routers/usage.py) — this router is the workspace-wide front door.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.models import (
    FeedbackDailyPoint,
    FeedbackRollup,
    FeedbackRollupItem,
    FeedbackWorkspaceSummary,
)
from backend.services import lakebase, system_tables

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feedback")


def _parse_daily_negatives(raw: Any) -> list[FeedbackDailyPoint]:
    """The SQL returns the daily_negatives column as a JSON-encoded array of
    {day, neg} structs. Parse it into a typed list, tolerating None / empty.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Could not parse daily_negatives: %r", raw[:200])
            return []
    if not isinstance(raw, list):
        return []
    points: list[FeedbackDailyPoint] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        day = entry.get("day")
        neg = entry.get("neg")
        if day is None or neg is None:
            continue
        try:
            points.append(FeedbackDailyPoint(day=_to_date(day), neg=int(neg)))
        except (ValueError, TypeError):
            continue
    return points


def _to_date(v: Any) -> date:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date()


def _to_datetime(v: Any) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get("/rollup")
async def get_rollup(days: int = 30, limit: int = 50) -> dict:
    """Return workspace-wide feedback summary + per-space rollup."""
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days must be between 1 and 365")
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")

    try:
        rows = await asyncio.to_thread(system_tables.feedback_rollup, days, limit)
    except Exception as e:
        logger.exception("feedback_rollup query failed")
        raise HTTPException(status_code=502, detail=f"system table query failed: {e}")

    # Look up space titles once (cached list, then dict for O(1) lookup).
    try:
        cached = await lakebase.list_cached_spaces()
        titles = {s["space_id"]: s.get("title") for s in cached}
    except Exception as e:
        logger.warning("space-cache lookup failed; titles will be missing: %s", e)
        titles = {}

    if not rows:
        return FeedbackRollup(
            days=days,
            summary=FeedbackWorkspaceSummary(
                total=0, positive=0, negative=0, pct_positive=None, spaces_with_negatives=0,
            ),
            items=[],
        ).model_dump(mode="json")

    # All rows share the same ws_* fields (CROSS JOIN with 1-row summary).
    ws_total = int(rows[0].get("ws_total") or 0)
    ws_positive = int(rows[0].get("ws_positive") or 0)
    ws_negative = int(rows[0].get("ws_negative") or 0)
    ws_spaces_neg = int(rows[0].get("ws_spaces_with_negatives") or 0)
    pct_positive = (ws_positive / ws_total) if ws_total > 0 else None

    items: list[FeedbackRollupItem] = []
    for r in rows:
        space_id = str(r.get("space_id") or "")
        if not space_id:
            continue
        items.append(FeedbackRollupItem(
            space_id=space_id,
            title=titles.get(space_id),
            total=int(r.get("total") or 0),
            positive=int(r.get("positive") or 0),
            negative=int(r.get("negative") or 0),
            last_negative_at=_to_datetime(r.get("last_negative_at")),
            daily_negatives=_parse_daily_negatives(r.get("daily_negatives")),
        ))

    return FeedbackRollup(
        days=days,
        summary=FeedbackWorkspaceSummary(
            total=ws_total,
            positive=ws_positive,
            negative=ws_negative,
            pct_positive=pct_positive,
            spaces_with_negatives=ws_spaces_neg,
        ),
        items=items,
    ).model_dump(mode="json")
