"""Lakebase (PostgreSQL) persistence for GenieWatch.

Schema name: `geniewatch`. System tables are the source of truth for usage,
cost, and lineage; Lakebase stores caches (space inventory, conversation/
message inventory) and user-set mappings (space -> MLflow experiment).

Forked from genie-workbench (auth + pool + token refresh logic kept verbatim
where possible). Schema is GenieWatch-specific.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory fallback (used when Lakebase is unavailable).
_memory_store: dict = {
    "space_cache": {},          # space_id -> dict
    "conversation_cache": {},   # (space_id, conversation_id) -> dict
    "message_cache": {},        # (space_id, conversation_id, message_id) -> dict
    "sync_watermark": {},       # resource -> dict
    "eval_mappings": {},        # space_id -> dict
    "daily_usage_rollup": {},   # (space_id, day) -> dict
}

_pool = None
_lakebase_available = False
_schema_retry_after: float = 0
_token_refresh_task: asyncio.Task | None = None
_current_token: str | None = None
_lakebase_autoscaling_endpoint: str | None = None
_lakebase_project_name: str | None = None
_conn_params: dict | None = None


def _generate_credential() -> tuple[str, str] | None:
    """Generate Lakebase credentials. Supports provisioned and autoscaling."""
    global _current_token
    try:
        from backend.services.auth import get_service_principal_client
        client = get_service_principal_client()

        if _lakebase_autoscaling_endpoint:
            cred = client.postgres.generate_database_credential(
                endpoint=_lakebase_autoscaling_endpoint,
            )
        else:
            instance_name = os.environ.get("LAKEBASE_INSTANCE_NAME", "")
            if not instance_name:
                return None
            cred = client.database.generate_database_credential(
                request_id=str(uuid.uuid4()),
                instance_names=[instance_name],
            )

        token = cred.token
        if not token:
            return None
        _current_token = token

        user = client.config.client_id or os.environ.get("DATABRICKS_CLIENT_ID", "")
        if not user:
            try:
                me = client.current_user.me()
                user = me.user_name or ""
            except Exception:
                pass
        if not user:
            return None
        return user, token
    except Exception as e:
        logger.warning(f"Lakebase credential generation failed: {e}")
        return None


async def _token_refresh_loop():
    """Refresh Lakebase token every 50 minutes (before 1-hour expiry)."""
    global _pool, _current_token
    while True:
        await asyncio.sleep(50 * 60)
        try:
            cred = _generate_credential()
            if not cred:
                logger.warning("Failed to refresh Lakebase token")
                continue
            user, token = cred
            _current_token = token
            if _conn_params is None or _pool is None:
                continue
            import asyncpg
            new_pool = await asyncpg.create_pool(
                host=_conn_params["host"],
                port=_conn_params["port"],
                database=_conn_params["database"],
                user=user,
                password=token,
                min_size=2,
                max_size=10,
                command_timeout=30,
                ssl="require",
            )
            old_pool = _pool
            _pool = new_pool
            if old_pool:
                await old_pool.close()
            logger.info("Lakebase token refreshed and pool recreated")
        except Exception as e:
            logger.warning(f"Lakebase token refresh error: {e}")


async def _ensure_schema():
    """Idempotently create all GenieWatch tables.

    Schema definition matches docs/architecture.md §3.
    """
    global _lakebase_available, _schema_retry_after
    if _pool is None:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS geniewatch")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS geniewatch.space_cache (
                    space_id     VARCHAR(64) PRIMARY KEY,
                    title        TEXT,
                    owner_email  TEXT,
                    description  TEXT,
                    permissions  JSONB,
                    last_seen_at TIMESTAMPTZ NOT NULL,
                    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_space_cache_owner ON geniewatch.space_cache(owner_email)"
            )

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS geniewatch.conversation_cache (
                    space_id        VARCHAR(64) NOT NULL,
                    conversation_id VARCHAR(64) NOT NULL,
                    user_email      TEXT,
                    created_at      TIMESTAMPTZ,
                    message_count   INT DEFAULT 0,
                    last_message_at TIMESTAMPTZ,
                    PRIMARY KEY (space_id, conversation_id)
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conv_cache_last ON geniewatch.conversation_cache(last_message_at DESC)"
            )

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS geniewatch.message_cache (
                    space_id        VARCHAR(64) NOT NULL,
                    conversation_id VARCHAR(64) NOT NULL,
                    message_id      VARCHAR(64) NOT NULL,
                    user_email      TEXT,
                    created_at      TIMESTAMPTZ,
                    status          TEXT,
                    has_sql         BOOLEAN,
                    feedback_rating TEXT,
                    PRIMARY KEY (space_id, conversation_id, message_id)
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS geniewatch.sync_watermark (
                    resource       VARCHAR(128) PRIMARY KEY,
                    last_synced_at TIMESTAMPTZ NOT NULL,
                    status         TEXT,
                    error          TEXT
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS geniewatch.eval_mappings (
                    space_id      VARCHAR(64) PRIMARY KEY,
                    experiment_id VARCHAR(64) NOT NULL,
                    created_by    TEXT NOT NULL,
                    created_at    TIMESTAMPTZ DEFAULT NOW(),
                    updated_at    TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS geniewatch.daily_usage_rollup (
                    space_id     VARCHAR(64) NOT NULL,
                    day          DATE NOT NULL,
                    queries      INT NOT NULL,
                    approx_dbus  DOUBLE PRECISION,
                    approx_usd   DOUBLE PRECISION,
                    feedback_pos INT NOT NULL DEFAULT 0,
                    feedback_neg INT NOT NULL DEFAULT 0,
                    PRIMARY KEY (space_id, day)
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rollup_day ON geniewatch.daily_usage_rollup(day DESC)"
            )

        _lakebase_available = True
        logger.info("Lakebase schema ready (geniewatch.*)")
    except Exception as e:
        logger.warning(f"Failed to ensure Lakebase schema: {e}. In-memory fallback active.")
        _lakebase_available = False
        _schema_retry_after = time.monotonic() + 30


async def _maybe_retry_schema():
    global _schema_retry_after
    if _lakebase_available or _pool is None:
        return
    if time.monotonic() < _schema_retry_after:
        return
    _schema_retry_after = time.monotonic() + 30
    await _ensure_schema()


async def init_pool():
    """Initialize asyncpg connection pool. Falls back gracefully if unavailable."""
    global _pool, _lakebase_available, _token_refresh_task
    global _lakebase_autoscaling_endpoint, _lakebase_project_name, _conn_params

    host = os.environ.get("LAKEBASE_HOST")
    if not host:
        logger.info("LAKEBASE_HOST not set — using in-memory fallback.")
        return

    if host.startswith("projects/") or "." not in host:
        from backend.services.auth import get_service_principal_client
        client = get_service_principal_client()

        if host.startswith("projects/"):
            _lakebase_autoscaling_endpoint = host
            _lakebase_project_name = host.split("/")[1]
            try:
                endpoint = client.postgres.get_endpoint(name=host)
                hosts = endpoint.status and endpoint.status.hosts
                resolved = hosts.host if hosts else None
                if not resolved:
                    logger.warning("Autoscaling endpoint has no host yet")
                    return
                host = resolved
            except Exception as e:
                logger.warning(f"Could not resolve Lakebase Autoscaling endpoint: {e}")
                return
        else:
            instance_name = os.environ.get("LAKEBASE_INSTANCE_NAME", "")
            if not instance_name:
                logger.warning("LAKEBASE_HOST requires resolution but LAKEBASE_INSTANCE_NAME not set")
                return
            try:
                instance = client.database.get_database_instance(name=instance_name)
                resolved = instance.read_write_dns
                if not resolved:
                    return
                host = resolved
            except Exception as e:
                logger.warning(f"Could not resolve Lakebase host: {e}")
                return

    password = os.environ.get("LAKEBASE_PASSWORD")
    user = os.environ.get("LAKEBASE_USER", "postgres")
    if not password:
        cred = _generate_credential()
        if cred:
            user, password = cred
        else:
            logger.warning("Lakebase has no password — using in-memory fallback")
            return

    port = int(os.environ.get("LAKEBASE_PORT", "5432"))
    database = os.environ.get("LAKEBASE_DATABASE", "databricks_postgres")
    _conn_params = {"host": host, "port": port, "database": database}

    logger.info(f"Connecting to Lakebase: host={host}, user={user[:12]}..., db={database}")
    try:
        import asyncpg
        _pool = await asyncpg.create_pool(
            host=host, port=port, database=database, user=user, password=password,
            min_size=2, max_size=25, command_timeout=30, timeout=10, ssl="require",
        )
        _lakebase_available = True
        await _ensure_schema()
        _token_refresh_task = asyncio.create_task(_token_refresh_loop())
    except Exception as e:
        logger.warning(f"Lakebase unavailable: {e}. In-memory fallback active.")
        _lakebase_available = False


async def close_pool():
    global _pool, _token_refresh_task
    if _token_refresh_task:
        _token_refresh_task.cancel()
        _token_refresh_task = None
    if _pool:
        await _pool.close()
        _pool = None


def is_available() -> bool:
    return _lakebase_available and _pool is not None


# ─── Space cache ───────────────────────────────────────────────────────────

async def upsert_space(space: dict) -> None:
    """Upsert into geniewatch.space_cache."""
    space_id = space["space_id"]
    if not is_available():
        _memory_store["space_cache"][space_id] = {
            **space,
            "updated_at": datetime.utcnow().isoformat(),
        }
        return
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO geniewatch.space_cache
                (space_id, title, owner_email, description, permissions, last_seen_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
            ON CONFLICT (space_id) DO UPDATE SET
                title        = EXCLUDED.title,
                owner_email  = EXCLUDED.owner_email,
                description  = EXCLUDED.description,
                permissions  = EXCLUDED.permissions,
                last_seen_at = NOW(),
                updated_at   = NOW()
        """,
            space_id,
            space.get("title"),
            space.get("owner_email"),
            space.get("description"),
            json.dumps(space.get("permissions") or []),
        )


async def list_cached_spaces() -> list[dict]:
    await _maybe_retry_schema()
    if not is_available():
        return [
            {**s, "permissions": s.get("permissions") or []}
            for s in _memory_store["space_cache"].values()
        ]
    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT space_id, title, owner_email, description, permissions,
                   last_seen_at, updated_at
            FROM geniewatch.space_cache
            ORDER BY last_seen_at DESC
        """)
        return [
            {
                "space_id": r["space_id"],
                "title": r["title"],
                "owner_email": r["owner_email"],
                "description": r["description"],
                "permissions": json.loads(r["permissions"]) if r["permissions"] else [],
                "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        ]


# ─── Conversation cache ────────────────────────────────────────────────────

async def upsert_conversation(conv: dict) -> None:
    if not is_available():
        key = (conv["space_id"], conv["conversation_id"])
        _memory_store["conversation_cache"][key] = conv
        return
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO geniewatch.conversation_cache
                (space_id, conversation_id, user_email, created_at, message_count, last_message_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (space_id, conversation_id) DO UPDATE SET
                user_email      = EXCLUDED.user_email,
                message_count   = EXCLUDED.message_count,
                last_message_at = EXCLUDED.last_message_at
        """,
            conv["space_id"], conv["conversation_id"],
            conv.get("user_email"),
            conv.get("created_at"),
            conv.get("message_count") or 0,
            conv.get("last_message_at"),
        )


async def list_conversations(space_id: str, limit: int = 100) -> list[dict]:
    if not is_available():
        out = [c for k, c in _memory_store["conversation_cache"].items() if k[0] == space_id]
        return sorted(out, key=lambda c: c.get("last_message_at") or "", reverse=True)[:limit]
    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT conversation_id, user_email, created_at, message_count, last_message_at
            FROM geniewatch.conversation_cache
            WHERE space_id = $1
            ORDER BY last_message_at DESC NULLS LAST
            LIMIT $2
        """, space_id, limit)
        return [
            {
                "conversation_id": r["conversation_id"],
                "user_email": r["user_email"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "message_count": r["message_count"],
                "last_message_at": r["last_message_at"].isoformat() if r["last_message_at"] else None,
            }
            for r in rows
        ]


async def upsert_message(msg: dict) -> None:
    if not is_available():
        key = (msg["space_id"], msg["conversation_id"], msg["message_id"])
        _memory_store["message_cache"][key] = msg
        return
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO geniewatch.message_cache
                (space_id, conversation_id, message_id, user_email, created_at, status, has_sql, feedback_rating)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (space_id, conversation_id, message_id) DO UPDATE SET
                status          = EXCLUDED.status,
                has_sql         = EXCLUDED.has_sql,
                feedback_rating = EXCLUDED.feedback_rating
        """,
            msg["space_id"], msg["conversation_id"], msg["message_id"],
            msg.get("user_email"),
            msg.get("created_at"),
            msg.get("status"),
            msg.get("has_sql"),
            msg.get("feedback_rating"),
        )


# ─── Sync watermark ────────────────────────────────────────────────────────

async def get_watermark(resource: str) -> Optional[dict]:
    if not is_available():
        return _memory_store["sync_watermark"].get(resource)
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT resource, last_synced_at, status, error FROM geniewatch.sync_watermark WHERE resource = $1",
            resource,
        )
        if not row:
            return None
        return {
            "resource": row["resource"],
            "last_synced_at": row["last_synced_at"].isoformat() if row["last_synced_at"] else None,
            "status": row["status"],
            "error": row["error"],
        }


async def set_watermark(resource: str, status: str, error: str | None = None) -> None:
    if not is_available():
        _memory_store["sync_watermark"][resource] = {
            "resource": resource,
            "last_synced_at": datetime.utcnow().isoformat(),
            "status": status,
            "error": error,
        }
        return
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO geniewatch.sync_watermark (resource, last_synced_at, status, error)
            VALUES ($1, NOW(), $2, $3)
            ON CONFLICT (resource) DO UPDATE SET
                last_synced_at = NOW(), status = EXCLUDED.status, error = EXCLUDED.error
        """, resource, status, error)


# ─── Eval mappings ─────────────────────────────────────────────────────────

async def get_eval_mapping(space_id: str) -> Optional[dict]:
    if not is_available():
        return _memory_store["eval_mappings"].get(space_id)
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT space_id, experiment_id, created_by, created_at, updated_at "
            "FROM geniewatch.eval_mappings WHERE space_id = $1",
            space_id,
        )
        if not row:
            return None
        return {
            "space_id": row["space_id"],
            "experiment_id": row["experiment_id"],
            "created_by": row["created_by"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }


async def upsert_eval_mapping(space_id: str, experiment_id: str, created_by: str) -> dict:
    record = {
        "space_id": space_id,
        "experiment_id": experiment_id,
        "created_by": created_by,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    if not is_available():
        _memory_store["eval_mappings"][space_id] = record
        return record
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO geniewatch.eval_mappings (space_id, experiment_id, created_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (space_id) DO UPDATE SET
                experiment_id = EXCLUDED.experiment_id,
                updated_at    = NOW()
        """, space_id, experiment_id, created_by)
    return record


async def delete_eval_mapping(space_id: str) -> None:
    if not is_available():
        _memory_store["eval_mappings"].pop(space_id, None)
        return
    async with _pool.acquire() as conn:
        await conn.execute("DELETE FROM geniewatch.eval_mappings WHERE space_id = $1", space_id)


# ─── Daily usage rollup (optional pre-aggregation) ─────────────────────────

async def upsert_daily_rollup(row: dict) -> None:
    if not is_available():
        _memory_store["daily_usage_rollup"][(row["space_id"], row["day"])] = row
        return
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO geniewatch.daily_usage_rollup
                (space_id, day, queries, approx_dbus, approx_usd, feedback_pos, feedback_neg)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (space_id, day) DO UPDATE SET
                queries      = EXCLUDED.queries,
                approx_dbus  = EXCLUDED.approx_dbus,
                approx_usd   = EXCLUDED.approx_usd,
                feedback_pos = EXCLUDED.feedback_pos,
                feedback_neg = EXCLUDED.feedback_neg
        """,
            row["space_id"], row["day"],
            row.get("queries") or 0,
            row.get("approx_dbus"),
            row.get("approx_usd"),
            row.get("feedback_pos") or 0,
            row.get("feedback_neg") or 0,
        )
