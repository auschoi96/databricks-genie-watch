# GenieWatch

Observability for Databricks Genie Spaces — usage, cost, evals, and resource lineage.

GenieWatch is a read-only Databricks App. It lists every Genie Space in a workspace, attributes cost per space (apportioned from warehouse-level billing), tracks usage (queries, conversations, feedback), surfaces eval runs from MLflow experiments mapped to a space, and rolls up which tables/views/metric views are referenced across all spaces.

It is the observability sibling to [databricks-genie-workbench](https://github.com/databricks-solutions/databricks-genie-workbench), which creates and optimizes spaces.

## What it shows

| Capability | Source | Notes |
|---|---|---|
| List spaces with status | `GET /api/2.0/genie/spaces` | OBO so each user sees only the spaces they can access |
| Cost per space | `system.query.history` × `system.billing.usage` | Warehouse-level billing apportioned by query duration |
| Usage / queries / latency / errors | `system.query.history` | Filter on `query_source.genie_space_id` |
| Conversations + messages | Genie REST API | Cached per-space in Lakebase (no workspace-wide list endpoint) |
| Feedback | `system.access.audit` | `service_name='aibiGenie'`, lag is ~1–4 hours |
| Evals | MLflow tracking | User-set `space_id → experiment_id` mapping |
| Configured resources | `serialized_space.data_sources` | Tables + metric views in the space config |
| Executed resources | `system.access.table_lineage` | Tables Genie actually queried; lag ~15–30 min |
| Workspace resource rollup | `system.access.table_lineage` | Top tables by `space_count` |

## Quick start

```bash
./scripts/install.sh         # Guided setup — writes .env.deploy, runs deploy
./scripts/deploy.sh           # Subsequent full deploys
./scripts/deploy.sh --update  # Code-only update
./scripts/deploy.sh --destroy # Tear down the app
```

The installer prompts for:
- Databricks CLI profile
- SQL warehouse (used to run system.* queries as the app SP)
- Optional Lakebase project name (for conversation cache + eval mappings)
- Optional embedded Cost Explorer dashboard ID

## Architecture

```
backend/
  main.py                    # FastAPI + OBO middleware + static SPA
  models.py                  # Pydantic v2 types
  routers/
    spaces.py                # /api/spaces*
    cost.py                  # /api/spaces/{id}/cost, /api/cost/top
    usage.py                 # /api/spaces/{id}/usage, /feedback
    resources.py             # /api/spaces/{id}/resources, /api/resources/rollup
    evals.py                 # /api/spaces/{id}/evals
    settings.py              # /api/settings/*
    admin.py                 # /api/admin/refresh-rollup
    auth.py                  # /api/auth/me, /api/auth/status
  services/
    auth.py                  # OBO ContextVar + SP fallback
    lakebase.py              # asyncpg pool, in-memory fallback, geniewatch.* schema
    genie_client.py          # /api/2.0/genie/spaces*
    conversations_client.py  # paginate conversations + messages, cache to Lakebase
    system_tables.py         # SQL wrappers for system.query.history, system.billing.usage,
                             # system.access.audit, system.access.table_lineage
    mlflow_client.py         # MLflow tracking server reads
    uc_client.py             # UC table metadata for resource enrichment
frontend/
  src/
    App.tsx                  # Spaces / Cost / Resources / Settings nav
    pages/                   # SpacesList, SpaceDetail, CostExplorer, ResourceRollup, Settings
    components/              # ui/* (Radix + CVA), DashboardEmbed
    lib/api.ts               # Typed fetch helpers, mirrors backend models
docs/
  architecture.md
  system-tables-grants.md    # GRANT statements the SP needs
  apportionment-caveat.md    # Why cost is approximate
```

## Permissions the app SP needs

```sql
-- One-time, run as a workspace admin (or any principal that can grant SELECT on system.*)
GRANT USE CATALOG ON CATALOG `system` TO `<sp-app-id>`;
GRANT USE SCHEMA  ON SCHEMA  `system`.`query`   TO `<sp-app-id>`;
GRANT USE SCHEMA  ON SCHEMA  `system`.`billing` TO `<sp-app-id>`;
GRANT USE SCHEMA  ON SCHEMA  `system`.`access`  TO `<sp-app-id>`;
GRANT SELECT ON TABLE `system`.`query`.`history`        TO `<sp-app-id>`;
GRANT SELECT ON TABLE `system`.`billing`.`usage`        TO `<sp-app-id>`;
GRANT SELECT ON TABLE `system`.`access`.`audit`         TO `<sp-app-id>`;
GRANT SELECT ON TABLE `system`.`access`.`table_lineage` TO `<sp-app-id>`;
```

`./scripts/grant_permissions.py` runs these for you.

## OBO scopes the user needs

- `dashboards.genie` — list spaces under user identity
- `catalog.{catalogs,schemas,tables}:read` — resource enrichment
- `iam.access-control:read` — read space ACLs

System-table queries always run as the SP. Per-space numbers are filtered in Python to the user-visible space IDs *before* being returned.

## Important caveats

1. **Cost is approximate.** Databricks bills warehouses, not queries. We apportion `(space_query_duration / warehouse_total_duration) × warehouse_day_dbus`. Serverless behaves slightly differently; values are best-effort.
2. **Audit-log lag.** Feedback events arrive in `system.access.audit` ~1–4 hours after they happen.
3. **Conversation enumeration.** The Genie API has no workspace-wide list — it's O(spaces × pages). The conversation cache is refreshed on demand from Settings.
4. **Eval mapping is manual.** Set the `space_id → experiment_id` link in Settings.
5. **System table retention is 365 days.** No GenieWatch-side retention policy needed.

## Status

This is the initial scaffold. Deploy it once, grant the SP the system table SELECTs, and the six core capabilities should populate as data arrives.
