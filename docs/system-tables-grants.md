# System table grants

GenieWatch reads from four system tables. The app's service principal must hold `SELECT` on each. `scripts/grant_permissions.py` runs these for you when you have admin rights; otherwise paste this into a SQL editor.

```sql
-- Replace <sp> with the app's service-principal application_id
-- (a UUID like 6b205849-2e28-41a3-bafe-7105b151ffc2). Find it in the
-- Databricks Apps UI or `databricks apps get <app-name>`.

GRANT USE CATALOG ON CATALOG `system` TO `<sp>`;

GRANT USE SCHEMA  ON SCHEMA  `system`.`query`   TO `<sp>`;
GRANT USE SCHEMA  ON SCHEMA  `system`.`billing` TO `<sp>`;
GRANT USE SCHEMA  ON SCHEMA  `system`.`access`  TO `<sp>`;

GRANT SELECT ON TABLE `system`.`query`.`history`            TO `<sp>`;
GRANT SELECT ON TABLE `system`.`billing`.`usage`            TO `<sp>`;
GRANT SELECT ON TABLE `system`.`access`.`audit`             TO `<sp>`;
GRANT SELECT ON TABLE `system`.`access`.`table_lineage`     TO `<sp>`;

-- Optional. If absent or ungrantable, the cost drill-down falls back to
-- workspace_id only (workspace_name shown as "—").
GRANT SELECT ON TABLE `system`.`access`.`workspaces_latest` TO `<sp>`;
```

## What each table is used for

| Table | GenieWatch uses |
|---|---|
| `system.query.history` | Cost (joined with billing), queries/latency/errors per space, top-N expensive queries |
| `system.billing.usage` | Per-warehouse-day DBUs and `list_price`, apportioned to spaces |
| `system.access.audit` | Genie feedback events (`service_name='aibiGenie'`, `action_name='updateConversationMessageFeedback'`) |
| `system.access.table_lineage` | Tables actually queried by Genie spaces — joined with the configured `serialized_space.data_sources` for the per-space resources tab and the workspace-wide rollup |
| `system.access.workspaces_latest` *(optional)* | Workspace name lookup for the cost drill-down. Best-effort — if the table or grant is absent the column gracefully falls back to `workspace_id` only |

## OBO scopes the *user* needs (separate from SP grants)

Set on the app via `databricks api patch /api/2.0/apps/<name>`:
- `sql`
- `dashboards.genie`
- `catalog.catalogs:read`, `catalog.schemas:read`, `catalog.tables:read`
- `iam.access-control:read`

`scripts/deploy.sh` configures these in the PATCH payload it sends to the Apps API after each deploy.
