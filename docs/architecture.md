# GenieWatch architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                        Databricks Apps platform                        │
│                                                                        │
│   ┌────────────────┐                                                   │
│   │  Browser /     │                                                   │
│   │  React SPA     │                                                   │
│   └───────┬────────┘                                                   │
│           │ /api/*                                                     │
│           ▼                                                            │
│   ┌────────────────────────────────────┐                               │
│   │  FastAPI                            │                               │
│   │  + OBOAuthMiddleware                │                               │
│   └──┬─────────┬─────────┬─────────┬────┘                               │
│      │         │         │         │                                    │
│      │  OBO    │  OBO    │  SP     │  SP                                │
│      ▼         ▼         ▼         ▼                                    │
│   ┌──────┐ ┌──────┐ ┌──────────┐ ┌──────────────────────┐               │
│   │Genie │ │ UC   │ │ MLflow   │ │ system.query.history │               │
│   │ API  │ │ API  │ │ tracking │ │ system.billing.usage │               │
│   │      │ │      │ │  server  │ │ system.access.audit  │               │
│   │      │ │      │ │          │ │ system.access.       │               │
│   │      │ │      │ │          │ │   table_lineage      │               │
│   └──────┘ └──────┘ └──────────┘ └──────────────────────┘               │
│                                       (via SQL warehouse)              │
│      ▲                                                                 │
│      │                                                                 │
│   ┌──┴────────────────────────────────┐                                │
│   │ Lakebase (asyncpg)                 │                                │
│   │   geniewatch.space_cache           │                                │
│   │   geniewatch.conversation_cache    │                                │
│   │   geniewatch.message_cache         │                                │
│   │   geniewatch.eval_mappings         │                                │
│   │   geniewatch.sync_watermark        │                                │
│   │   geniewatch.daily_usage_rollup    │                                │
│   └────────────────────────────────────┘                                │
└───────────────────────────────────────────────────────────────────────┘
```

## Data flow per page

| Page | Data sources | Auth |
|---|---|---|
| Spaces list | Genie API (live) → cache; system.query.history; system.billing.usage; system.access.audit | OBO for live list; SP for system tables; merge in Python and filter to OBO-visible IDs |
| Space → Overview | Genie API + UC | OBO |
| Space → Usage | system.query.history; system.access.audit; conversation_cache | SP for the first two; cache reads bypass auth |
| Space → Cost | system.query.history × system.billing.usage | SP |
| Space → Resources | serialized_space (Genie API) + system.access.table_lineage | OBO + SP |
| Space → Evals | eval_mappings + MLflow | SP for MLflow (tracking server is workspace-scoped) |
| Cost Explorer | system.query.history + Lakeview embed | SP |
| Resource Rollup | system.access.table_lineage | SP |
| Settings | Lakebase mappings; MLflow validation | SP |

## Why two auth identities?

- **OBO (per-user)** ensures users only see Genie Spaces they have access to. The space list comes from `/api/2.0/genie/spaces` under OBO so it respects ACL.
- **SP (service principal)** is required for `system.*` reads. Workspaces don't grant `SELECT` on system tables to all users. The SP holds those grants once, and the app filters down to user-visible IDs in Python.

If the OBO call fails with a scope error, the Genie client falls back to SP — the *list* stops being filtered to the user's view, but the user still sees nothing they can't query through SP perms. Surface this to the user with a banner if it fires repeatedly.

## Lakebase schema

See `backend/services/lakebase.py::_ensure_schema` for the authoritative DDL.

System tables are the source of truth for cost/usage/feedback/lineage; Lakebase only stores:
1. **Caches** with implicit TTLs (refreshed on demand or by a scheduled job in Phase 3).
2. **User-set mappings** (`eval_mappings`).
3. **Sync watermarks** for incremental refreshes.

If Lakebase is unavailable the app falls back to in-memory dicts — caches reset on restart, system-table-derived numbers still work.
