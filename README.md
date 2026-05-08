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
| Resource lineage graph | `system.access.table_lineage` | Bipartite Genie Space ↔ Resource graph; spans the metastore (cross-workspace data) |
| Workspace breakdown on cost | `system.access.workspaces_latest` | Optional column resolving `workspace_id` → `workspace_name` on the Cost drill-down |

## Resource Lineage Graph

The Resources page has a **Graph** tab that renders a bipartite force-directed graph of Genie Spaces ↔ Resources from `system.access.table_lineage`. Built with `react-force-graph-2d`. The sidebar exposes:

- **Workspace** filter — narrows spaces to the selected workspaces (cross-workspace data is metastore-scoped, so multi-workspace metastores show many).
- **Genie Spaces** filter — multi-select with search; auto-narrows to spaces in the active workspaces.
- **Min spaces per resource** slider — hides resource nodes referenced by fewer than N spaces. Set to 2+ to surface tables shared across spaces (potential redundancy candidates). The slider cascades through both dropdowns.
- **Hide spaces with no title** toggle — drops spaces whose title couldn't be resolved by `list_genie_spaces`. Catches both trashed spaces (lineage events persist after deletion) and cross-workspace spaces invisible to the calling user.
- **Resource scope** — three cascading dropdowns over the parsed `catalog.schema.table` parts of every resource: Catalog, Schema, Table. Selecting a catalog narrows schemas to those catalogs; selecting a schema narrows tables to those schemas. Useful for zooming into a specific area of UC.

Hover any node to highlight its neighborhood; node size is log-scaled by query volume, with Genie Space nodes ~1.4× the radius of resource nodes for emphasis.

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
    resources.py             # /api/spaces/{id}/resources, /api/resources/rollup, /api/resources/graph
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
                             # system.access.audit, system.access.table_lineage,
                             # system.access.workspaces_latest (best-effort)
    mlflow_client.py         # MLflow tracking server reads
    uc_client.py             # UC table metadata for resource enrichment
frontend/
  src/
    App.tsx                  # Spaces / Cost / Resources / Settings nav
    pages/                   # SpacesList, SpaceDetail, CostExplorer, ResourceRollup,
                             # ResourceGraphView, Settings
    components/              # ui/* (Radix + CVA), DashboardEmbed
    lib/api.ts               # Typed fetch helpers, mirrors backend models
docs/
  architecture.md
  system-tables-grants.md    # GRANT statements the SP needs
  apportionment-caveat.md    # Why cost is approximate
```

## Permissions the app SP needs

### System tables (required)

```sql
-- One-time, run as a workspace admin (or any principal that can grant SELECT on system.*)
GRANT USE CATALOG ON CATALOG `system` TO `<sp-app-id>`;
GRANT USE SCHEMA  ON SCHEMA  `system`.`query`   TO `<sp-app-id>`;
GRANT USE SCHEMA  ON SCHEMA  `system`.`billing` TO `<sp-app-id>`;
GRANT USE SCHEMA  ON SCHEMA  `system`.`access`  TO `<sp-app-id>`;
GRANT SELECT ON TABLE `system`.`query`.`history`            TO `<sp-app-id>`;
GRANT SELECT ON TABLE `system`.`billing`.`usage`            TO `<sp-app-id>`;
GRANT SELECT ON TABLE `system`.`access`.`audit`             TO `<sp-app-id>`;
GRANT SELECT ON TABLE `system`.`access`.`table_lineage`     TO `<sp-app-id>`;

-- Optional. Powers the Cost drill-down "Workspace" column. If absent or
-- ungrantable, the column falls back to workspace_id (no functional regression).
GRANT SELECT ON TABLE `system`.`access`.`workspaces_latest` TO `<sp-app-id>`;
```

`./scripts/grant_permissions.py` runs all of the above for you.

### Lakebase (only when `WATCH_LAKEBASE_INSTANCE` is set)

```sql
-- Run as a Lakebase admin against databricks_postgres.
GRANT CONNECT ON DATABASE databricks_postgres TO "<sp-app-id>";
GRANT CREATE  ON DATABASE databricks_postgres TO "<sp-app-id>";
```

`./scripts/setup_lakebase.py` runs these on first deploy (the deployer needs Lakebase admin rights). Without Lakebase, conversation cache and eval mappings fall back to in-memory storage and don't persist across restarts.

### Genie Space access

The SP also needs to be able to *see* the Genie Spaces it queries. Two paths:

- **OBO works for most reads** — the user's identity is used to list spaces and read serialized configs, so per-user visibility is enforced automatically.
- **SP fallback** — when the OBO token lacks the `genie` scope, the app retries with the SP. For that to succeed, the SP must hold at least `CAN_VIEW` on the relevant Genie Spaces (workspace admin trivially satisfies this).

## OBO scopes the user needs

`scripts/deploy.sh` configures these on every deploy via `PATCH /api/2.0/apps/<name>` (see `deploy.sh:251`):

- `sql` — execute SQL statements via SDK
- `dashboards.genie` — list spaces under user identity
- `catalog.catalogs:read`, `catalog.schemas:read`, `catalog.tables:read` — resource enrichment

Note: space ACL reads (`/api/2.0/permissions/genie/{id}`) fall through to the SP when the user token can't authorize them — no OBO scope is configured for `iam.access-control:read` and none is required for the app to function.

System-table queries always run as the SP. Per-space numbers are filtered in Python to the user-visible space IDs *before* being returned.

## Important caveats

1. **Cost is approximate.** Databricks bills warehouses, not queries. We apportion `(space_query_duration / warehouse_total_duration) × warehouse_day_dbus`. Serverless behaves slightly differently; values are best-effort.
2. **Audit-log lag.** Feedback events arrive in `system.access.audit` ~1–4 hours after they happen.
3. **Conversation enumeration.** The Genie API has no workspace-wide list — it's O(spaces × pages). The conversation cache is refreshed on demand from Settings.
4. **Eval mapping is manual.** Set the `space_id → experiment_id` link in Settings.
5. **System table retention is 365 days.** No GenieWatch-side retention policy needed.

