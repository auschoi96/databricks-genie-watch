"""System-table queries for GenieWatch.

Reads:
  - system.query.history          (cost / usage / queries per space)
  - system.billing.usage          (warehouse-level billing apportioned to spaces)
  - system.access.audit           (Genie feedback events)
  - system.access.table_lineage   (executed-resource attribution)

All queries run as the *service principal* — system tables aren't usually
visible under OBO. The SP must hold:
  USE CATALOG system; USE SCHEMA system.{query,billing,access};
  SELECT on each table above.

See `docs/system-tables-grants.md` for the GRANT statements.

Implementation notes:
  - Uses WorkspaceClient.statement_execution.execute_statement (sync API,
    polled via wait_timeout=30s by the SDK). For long aggregations consider
    upgrading to the polling helper.
  - `:param`-style placeholders are passed as `parameters=[...]` so the
    server escapes them — never inline user-supplied values.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState

from backend.services.auth import get_service_principal_client

logger = logging.getLogger(__name__)


# ─── In-process TTL cache ─────────────────────────────────────────────────
#
# System-table queries are expensive (30-60s on a busy shared warehouse).
# Cache the *successful* result of each (sql, parameters) pair for a short
# window so a user clicking between tabs on the same space doesn't pay
# the latency twice. Keyed by SQL + JSON-encoded parameter bag.
# Eviction: lazy on read; cap at _CACHE_MAX entries.

_CACHE_TTL_SECONDS = 300  # 5 minutes
_CACHE_MAX = 256
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _cache_key(sql: str, parameters: list[StatementParameterListItem]) -> str:
    bag = sorted([(p.name, p.value, getattr(p.type, "value", str(p.type))) for p in parameters])
    return f"{hash(sql)}|{json.dumps(bag)}"


def _cache_get(key: str) -> list[dict[str, Any]] | None:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        ts, rows = entry
        if time.monotonic() - ts > _CACHE_TTL_SECONDS:
            _CACHE.pop(key, None)
            return None
        return rows


def _cache_put(key: str, rows: list[dict[str, Any]]) -> None:
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            # Drop the oldest (lazy LRU — works fine at this scale)
            oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
            _CACHE.pop(oldest, None)
        _CACHE[key] = (time.monotonic(), rows)


def _warehouse_id() -> str:
    wh = os.environ.get("SQL_WAREHOUSE_ID", "").strip()
    if not wh:
        raise RuntimeError("SQL_WAREHOUSE_ID env var is empty — system table queries cannot run.")
    return wh


def _client() -> WorkspaceClient:
    """SP client — system tables are not OBO-readable in most workspaces."""
    return get_service_principal_client()


def _run(
    sql: str,
    parameters: list[StatementParameterListItem],
    poll_total_seconds: int = 90,
    poll_interval_seconds: float = 2.0,
) -> list[dict[str, Any]]:
    """Execute a single statement, polling until completion. Return rows as dicts.

    Result of each (sql, params) is cached in-process for _CACHE_TTL_SECONDS
    so a user clicking between tabs on the same space gets instant subsequent
    loads. The first call on a fresh warehouse can still take 30-60s.
    """
    key = _cache_key(sql, parameters)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    client = _client()
    resp = client.statement_execution.execute_statement(
        warehouse_id=_warehouse_id(),
        statement=sql,
        parameters=parameters,
        wait_timeout="50s",
    )

    statement_id = resp.statement_id if resp else None
    deadline = time.monotonic() + poll_total_seconds
    while resp and resp.status and resp.status.state in (
        StatementState.PENDING, StatementState.RUNNING,
    ):
        if time.monotonic() > deadline or not statement_id:
            logger.warning(
                "system-table query %s still %s after %ss; returning [].",
                statement_id, resp.status.state, poll_total_seconds,
            )
            try:
                client.statement_execution.cancel_execution(statement_id=statement_id)
            except Exception:
                pass
            return []
        time.sleep(poll_interval_seconds)
        resp = client.statement_execution.get_statement(statement_id=statement_id)

    if resp is None or resp.status is None:
        return []
    state = resp.status.state
    if state != StatementState.SUCCEEDED:
        err = resp.status.error
        msg = err.message if err else state
        logger.warning("system-table query %s ended in %s: %s", statement_id, state, msg)
        return []

    if not resp.result or not resp.result.data_array:
        return []
    schema = resp.manifest.schema if resp.manifest else None
    if schema is None or schema.columns is None:
        return []
    cols = [c.name for c in schema.columns]
    rows = [
        {cols[i]: row[i] for i in range(len(cols))}
        for row in resp.result.data_array
    ]
    _cache_put(key, rows)
    return rows


def _p(name: str, value: Any, value_type: str = "STRING") -> StatementParameterListItem:
    return StatementParameterListItem(name=name, value=str(value), type=value_type)


# ─── Cost ─────────────────────────────────────────────────────────────────

_COST_PER_SPACE_SQL = """
WITH q AS (
    SELECT date_trunc('day', start_time) AS d,
           compute.warehouse_id AS wh,
           SUM(total_duration_ms) AS dur_ms,
           COUNT(*) AS n
    FROM system.query.history
    WHERE query_source.genie_space_id = :space_id
      AND start_time >= current_date() - :days
    GROUP BY 1, 2
), wt AS (
    SELECT date_trunc('day', start_time) AS d,
           compute.warehouse_id AS wh,
           SUM(total_duration_ms) AS total_ms
    FROM system.query.history
    WHERE start_time >= current_date() - :days
    GROUP BY 1, 2
), bill AS (
    SELECT date_trunc('day', u.usage_start_time) AS d,
           u.usage_metadata.warehouse_id AS wh,
           SUM(u.usage_quantity) AS dbus,
           SUM(u.usage_quantity * COALESCE(p.pricing.default, 0)) AS approx_usd
    FROM system.billing.usage u
    LEFT JOIN system.billing.list_prices p
      ON u.sku_name = p.sku_name
     AND u.cloud = p.cloud
     AND u.usage_start_time >= p.price_start_time
     AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)
    WHERE u.usage_metadata.warehouse_id IS NOT NULL
      AND u.usage_start_time >= current_date() - :days
    GROUP BY 1, 2
)
SELECT q.d AS day,
       q.wh AS warehouse_id,
       q.n AS query_count,
       (q.dur_ms / NULLIF(wt.total_ms, 0)) * COALESCE(bill.dbus, 0)        AS approx_dbus,
       (q.dur_ms / NULLIF(wt.total_ms, 0)) * COALESCE(bill.approx_usd, 0)  AS approx_usd
FROM q JOIN wt USING (d, wh) LEFT JOIN bill USING (d, wh)
ORDER BY q.d
"""


def cost_per_space(space_id: str, days: int = 7) -> list[dict[str, Any]]:
    return _run(_COST_PER_SPACE_SQL, [
        _p("space_id", space_id),
        _p("days", days, "INT"),
    ])


_TOP_SPENDERS_SQL = """
WITH q AS (
    SELECT query_source.genie_space_id AS space_id,
           compute.warehouse_id AS wh,
           SUM(total_duration_ms) AS dur_ms,
           COUNT(*) AS n
    FROM system.query.history
    WHERE query_source.genie_space_id IS NOT NULL
      AND start_time >= current_date() - :days
    GROUP BY 1, 2
), wt AS (
    SELECT compute.warehouse_id AS wh,
           SUM(total_duration_ms) AS total_ms
    FROM system.query.history
    WHERE start_time >= current_date() - :days
    GROUP BY 1
), bill AS (
    SELECT u.usage_metadata.warehouse_id AS wh,
           SUM(u.usage_quantity * COALESCE(p.pricing.default, 0)) AS approx_usd
    FROM system.billing.usage u
    LEFT JOIN system.billing.list_prices p
      ON u.sku_name = p.sku_name
     AND u.cloud = p.cloud
     AND u.usage_start_time >= p.price_start_time
     AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)
    WHERE u.usage_metadata.warehouse_id IS NOT NULL
      AND u.usage_start_time >= current_date() - :days
    GROUP BY 1
)
SELECT q.space_id,
       SUM(q.n) AS query_count,
       SUM((q.dur_ms / NULLIF(wt.total_ms, 0)) * COALESCE(bill.approx_usd, 0)) AS approx_usd
FROM q JOIN wt USING (wh) LEFT JOIN bill USING (wh)
GROUP BY q.space_id
ORDER BY approx_usd DESC NULLS LAST
LIMIT :limit
"""


def top_spenders(days: int = 7, limit: int = 10) -> list[dict[str, Any]]:
    return _run(_TOP_SPENDERS_SQL, [
        _p("days", days, "INT"),
        _p("limit", limit, "INT"),
    ])


# ─── Usage / queries / latency / errors ───────────────────────────────────

_USAGE_PER_SPACE_SQL = """
SELECT date_trunc('day', start_time) AS day,
       COUNT(*) AS queries,
       APPROX_PERCENTILE(total_duration_ms, 0.5) AS p50_ms,
       APPROX_PERCENTILE(total_duration_ms, 0.95) AS p95_ms,
       SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) AS errors,
       COUNT(DISTINCT executed_by) AS distinct_users
FROM system.query.history
WHERE query_source.genie_space_id = :space_id
  AND start_time >= current_date() - :days
GROUP BY 1
ORDER BY 1
"""


def usage_per_space(space_id: str, days: int = 30) -> list[dict[str, Any]]:
    return _run(_USAGE_PER_SPACE_SQL, [
        _p("space_id", space_id),
        _p("days", days, "INT"),
    ])


_USAGE_SUMMARY_SQL = """
SELECT
    query_source.genie_space_id AS space_id,
    COUNT(*) AS queries,
    COUNT(DISTINCT executed_by) AS distinct_users,
    MAX(start_time) AS last_query_at
FROM system.query.history
WHERE query_source.genie_space_id IS NOT NULL
  AND start_time >= current_date() - :days
GROUP BY 1
"""


def usage_summary_all_spaces(days: int = 7) -> list[dict[str, Any]]:
    return _run(_USAGE_SUMMARY_SQL, [_p("days", days, "INT")])


_TOP_QUERIES_SQL = """
SELECT statement_id,
       executed_by,
       start_time,
       total_duration_ms,
       execution_status,
       statement_text
FROM system.query.history
WHERE query_source.genie_space_id = :space_id
  AND start_time >= current_date() - :days
ORDER BY total_duration_ms DESC NULLS LAST
LIMIT :limit
"""


def top_expensive_queries(space_id: str, days: int = 7, limit: int = 20) -> list[dict[str, Any]]:
    return _run(_TOP_QUERIES_SQL, [
        _p("space_id", space_id),
        _p("days", days, "INT"),
        _p("limit", limit, "INT"),
    ])


# ─── Feedback (audit log) ─────────────────────────────────────────────────

_FEEDBACK_PER_SPACE_SQL = """
SELECT event_time,
       user_identity.email AS user_email,
       request_params.space_id AS space_id,
       request_params.feedback_rating AS rating,
       request_params.comment AS comment,
       request_params.message_id AS message_id,
       request_params.conversation_id AS conversation_id
FROM system.access.audit
WHERE service_name = 'aibiGenie'
  AND action_name = 'updateConversationMessageFeedback'
  AND request_params.space_id = :space_id
  AND event_time >= current_date() - :days
ORDER BY event_time DESC
LIMIT :limit
"""


def feedback_per_space(space_id: str, days: int = 30, limit: int = 200) -> list[dict[str, Any]]:
    return _run(_FEEDBACK_PER_SPACE_SQL, [
        _p("space_id", space_id),
        _p("days", days, "INT"),
        _p("limit", limit, "INT"),
    ])


_FEEDBACK_SUMMARY_SQL = """
SELECT request_params.space_id AS space_id,
       SUM(CASE WHEN request_params.feedback_rating = 'POSITIVE' THEN 1 ELSE 0 END) AS pos,
       SUM(CASE WHEN request_params.feedback_rating = 'NEGATIVE' THEN 1 ELSE 0 END) AS neg,
       COUNT(*) AS total
FROM system.access.audit
WHERE service_name = 'aibiGenie'
  AND action_name = 'updateConversationMessageFeedback'
  AND event_time >= current_date() - :days
GROUP BY 1
"""


def feedback_summary_all_spaces(days: int = 7) -> list[dict[str, Any]]:
    return _run(_FEEDBACK_SUMMARY_SQL, [_p("days", days, "INT")])


# ─── Lineage / executed resources ─────────────────────────────────────────

_EXECUTED_RESOURCES_SQL = """
SELECT entity_metadata.genie_space_id AS space_id,
       source_table_full_name AS full_name,
       COUNT(*) AS query_count,
       MAX(event_time) AS last_used
FROM system.access.table_lineage
WHERE entity_metadata.genie_space_id = :space_id
  AND source_table_full_name IS NOT NULL
  AND event_time >= current_date() - :days
GROUP BY 1, 2
ORDER BY query_count DESC
"""


def executed_resources(space_id: str, days: int = 30) -> list[dict[str, Any]]:
    return _run(_EXECUTED_RESOURCES_SQL, [
        _p("space_id", space_id),
        _p("days", days, "INT"),
    ])


_RESOURCE_ROLLUP_SQL = """
SELECT source_table_full_name AS full_name,
       COUNT(DISTINCT entity_metadata.genie_space_id) AS space_count,
       COUNT(*) AS query_count_total,
       MAX(event_time) AS last_used
FROM system.access.table_lineage
WHERE entity_metadata.genie_space_id IS NOT NULL
  AND source_table_full_name IS NOT NULL
  AND event_time >= current_date() - :days
GROUP BY 1
ORDER BY space_count DESC, query_count_total DESC
LIMIT :limit
"""


def resource_rollup(days: int = 30, limit: int = 50) -> list[dict[str, Any]]:
    return _run(_RESOURCE_ROLLUP_SQL, [
        _p("days", days, "INT"),
        _p("limit", limit, "INT"),
    ])


_RESOURCE_SPACES_SQL = """
SELECT DISTINCT entity_metadata.genie_space_id AS space_id
FROM system.access.table_lineage
WHERE source_table_full_name = :full_name
  AND entity_metadata.genie_space_id IS NOT NULL
  AND event_time >= current_date() - :days
"""


def spaces_using_resource(full_name: str, days: int = 30) -> list[str]:
    rows = _run(_RESOURCE_SPACES_SQL, [
        _p("full_name", full_name),
        _p("days", days, "INT"),
    ])
    return [r["space_id"] for r in rows if r.get("space_id")]
