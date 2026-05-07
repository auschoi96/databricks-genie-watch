# GenieWatch

Read-only observability Databricks App for Genie Spaces. Sibling to `databricks-genie-workbench` (which creates and optimizes spaces) — GenieWatch only reads.

## Critical rules

- **Do NOT run `uvicorn` locally.** The app needs Databricks OBO auth, system table grants, and Lakebase.
- **Do NOT use `npm install` in scripts.** Use `npm ci` so lockfiles stay authoritative.
- **Do NOT edit `requirements.txt` manually.** It's gitignored and regenerated from `uv.lock` if needed; the platform uses `uv sync`.
- All testing is done by deploying to a workspace.
- System table queries (`system.query.history`, `system.billing.usage`, `system.access.audit`, `system.access.table_lineage`) **always run as the SP** — OBO doesn't have grants for these by default. The space *list* uses OBO so users only see their own spaces; SP-side numbers are filtered in Python before being returned.

## Commands

```bash
uv sync --frozen                          # Install Python deps from uv.lock
cd frontend && npm ci && npm run build    # Build frontend

./scripts/install.sh                      # Guided first-time setup
./scripts/deploy.sh                       # Full deploy
./scripts/deploy.sh --update              # Code-only update
./scripts/deploy.sh --destroy             # Tear down the app
```

## Architecture (one-liner per file)

```
backend/main.py                       FastAPI entry; OBO middleware; SPA static fallback.
backend/models.py                     Pydantic v2 — keep in sync with frontend/src/types/api.ts.
backend/services/auth.py              OBO ContextVar; SP fallback for system tables / Genie scope errors.
backend/services/lakebase.py          asyncpg pool + in-memory fallback; geniewatch.* schema.
backend/services/genie_client.py      Genie REST: list spaces, get space, list ACLs.
backend/services/conversations_client.py
                                      Paginate /conversations + /messages; cache to Lakebase.
backend/services/system_tables.py     SQL wrappers for cost/usage/feedback/lineage.
backend/services/mlflow_client.py     MLflow tracking server reads (eval runs).
backend/services/uc_client.py         UC table metadata for resource enrichment.
backend/routers/spaces.py             /api/spaces — list (OBO+SP join), detail, refresh.
backend/routers/cost.py               /api/spaces/{id}/cost, /api/cost/top, top-queries.
backend/routers/usage.py              /api/spaces/{id}/usage, /feedback.
backend/routers/resources.py          /api/spaces/{id}/resources, /api/resources/rollup.
backend/routers/evals.py              /api/spaces/{id}/evals (uses lakebase eval_mappings + mlflow_client).
backend/routers/settings.py           /api/settings/health, /eval-mapping/{id}, /cache/refresh.
backend/routers/admin.py              /api/admin/refresh-rollup (SP-only daily rollup recompute).
```

## Key patterns

### OBO vs SP routing

- **OBO** (per-user): `genie_client.list_genie_spaces()`, `get_genie_space()`, `list_space_permissions()`. Falls back to SP if the OBO token lacks the `genie` scope.
- **SP only**: every `system_tables.*` call. The user identity is preserved only for the live space-list — SP-side numbers are filtered in Python to user-visible space IDs before being returned.

### Lakebase as cache

- `space_cache`, `conversation_cache`, `message_cache` — grow from Genie API.
- `eval_mappings` — user-set, persisted across deploys.
- `daily_usage_rollup` — optional pre-aggregation, refreshed by `/api/admin/refresh-rollup`.
- `sync_watermark` — tracks per-space conversation sync progress.

When `LAKEBASE_HOST` is unset, every accessor falls back to in-memory dicts (ephemeral). The app stays usable for the live-system-table parts but loses conversation drill-down and eval mappings.

### Cost apportionment

Cost is approximate. Per `services/system_tables.cost_per_space`:
- Per (day, warehouse): space DBUs ≈ `(space_duration_ms / warehouse_total_duration_ms) × billing_dbus`.
- USD ≈ `dbus × list_price` from `system.billing.usage.list_price`.
- Disclaimer banner is shown on every cost number; see `docs/apportionment-caveat.md`.

## Editing the data layer

If you change any SQL in `services/system_tables.py`, update:
- The corresponding Pydantic model in `backend/models.py`.
- The TS interface in `frontend/src/types/api.ts`.
- The relevant page in `frontend/src/pages/`.

If you add a new system table query, also update `docs/system-tables-grants.md` so the SP gets `SELECT` on it.

## References

- Genie REST API: https://docs.databricks.com/aws/en/genie/conversation-api
- system.query.history schema: https://docs.databricks.com/aws/en/admin/system-tables/query-history
- system.billing.usage schema: https://docs.databricks.com/aws/en/admin/system-tables/billing
- system.access.audit (Genie events): https://docs.databricks.com/aws/en/ai-bi/admin/audit
- system.access.table_lineage: https://docs.databricks.com/aws/en/admin/system-tables/lineage
- MLflow GenAI eval: https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/concepts/eval-harness
