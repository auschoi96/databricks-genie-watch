"""Usage router: queries / latency / errors / conversations / feedback."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from backend.models import (
    Conversation,
    FeedbackEvent,
    FeedbackSummary,
    UsagePoint,
    UsageRollup,
)
from backend.routers._validators import validate_days, validate_space_id
from backend.services import lakebase, system_tables

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/spaces/{space_id}/usage")
async def get_space_usage(
    space_id: str,
    days: int = Query(30, ge=1, le=365),
) -> dict:
    sid = validate_space_id(space_id)
    days = validate_days(days, default=30, max_days=365)

    try:
        usage_rows = system_tables.usage_per_space(sid, days=days)
    except Exception as e:
        logger.warning("usage_per_space failed: %s", e)
        usage_rows = []

    series = [
        UsagePoint(
            day=r["day"],
            queries=int(r.get("queries") or 0),
            p50_ms=_f(r.get("p50_ms")),
            p95_ms=_f(r.get("p95_ms")),
            errors=int(r.get("errors") or 0),
            distinct_users=int(r.get("distinct_users") or 0),
        )
        for r in usage_rows
    ]
    total_q = sum(p.queries for p in series)
    total_err = sum(p.errors for p in series)
    distinct_users = max((p.distinct_users for p in series), default=0)

    # Feedback
    try:
        fb_events = system_tables.feedback_per_space(sid, days=days, limit=200)
    except Exception as e:
        logger.warning("feedback_per_space failed: %s", e)
        fb_events = []
    fb_objs = [
        FeedbackEvent(
            event_time=e["event_time"],
            user_email=e.get("user_email"),
            rating=e.get("rating"),
            comment=e.get("comment"),
            message_id=e.get("message_id"),
            conversation_id=e.get("conversation_id"),
        )
        for e in fb_events
    ]
    pos = sum(1 for f in fb_objs if (f.rating or "").upper() == "POSITIVE")
    neg = sum(1 for f in fb_objs if (f.rating or "").upper() == "NEGATIVE")
    fb_summary = FeedbackSummary(
        positive=pos, negative=neg, total=len(fb_objs), sample=fb_objs[:50],
    )

    # Conversations from Lakebase cache (sync triggered by /api/settings/cache/refresh)
    convo_rows = await lakebase.list_conversations(sid, limit=50)
    convos = [Conversation(**c) for c in convo_rows]

    return UsageRollup(
        space_id=sid,
        days=days,
        total_queries=total_q,
        total_errors=total_err,
        distinct_users=distinct_users,
        time_series=series,
        feedback=fb_summary,
        conversations=convos,
    ).model_dump(mode="json")


@router.get("/spaces/{space_id}/feedback")
async def get_feedback(
    space_id: str,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(200, ge=1, le=2000),
) -> list[dict]:
    sid = validate_space_id(space_id)
    days = validate_days(days, default=30)
    rows = system_tables.feedback_per_space(sid, days=days, limit=limit)
    return [
        FeedbackEvent(
            event_time=e["event_time"],
            user_email=e.get("user_email"),
            rating=e.get("rating"),
            comment=e.get("comment"),
            message_id=e.get("message_id"),
            conversation_id=e.get("conversation_id"),
        ).model_dump(mode="json")
        for e in rows
    ]


def _f(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
