#!/usr/bin/env python3
"""
Grant the GenieWatch service principal the SELECTs it needs on system tables.

Run as a workspace admin (or any principal with USE CATALOG on `system` and
GRANT SELECT on the listed tables). Best-effort — failures are reported but
don't abort the deploy. The user can re-run the failing GRANT commands by
hand from `docs/system-tables-grants.md`.
"""
from __future__ import annotations

import argparse
import sys

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError


SYSTEM_TABLES = [
    "system.query.history",
    "system.billing.usage",
    "system.access.audit",
    "system.access.table_lineage",
    "system.access.workspaces_latest",
]

SYSTEM_SCHEMAS = [
    "system.query",
    "system.billing",
    "system.access",
]


def grant(client: WorkspaceClient, warehouse_id: str, sql: str) -> None:
    """Run a single GRANT statement; print outcome."""
    try:
        client.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=sql,
            wait_timeout="30s",
        )
        print(f"  ✓ {sql}")
    except DatabricksError as e:
        print(f"  ⚠ {sql}\n     → {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="DEFAULT")
    parser.add_argument("--sp-client-id", required=True,
                        help="Service principal application id (UUID).")
    parser.add_argument("--warehouse-id", required=True,
                        help="SQL warehouse to run the GRANTs on.")
    args = parser.parse_args()

    sp = args.sp_client_id
    client = WorkspaceClient(profile=args.profile)

    print(f"Granting SELECT on system tables to SP `{sp}` via warehouse {args.warehouse_id}...")
    grant(client, args.warehouse_id, f"GRANT USE CATALOG ON CATALOG `system` TO `{sp}`")
    for schema in SYSTEM_SCHEMAS:
        cat, sch = schema.split(".")
        grant(client, args.warehouse_id, f"GRANT USE SCHEMA ON SCHEMA `{cat}`.`{sch}` TO `{sp}`")
    for table in SYSTEM_TABLES:
        cat, sch, tbl = table.split(".")
        grant(client, args.warehouse_id, f"GRANT SELECT ON TABLE `{cat}`.`{sch}`.`{tbl}` TO `{sp}`")

    return 0


if __name__ == "__main__":
    sys.exit(main())
