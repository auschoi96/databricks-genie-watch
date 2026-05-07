#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# deploy-config.sh — shared configuration for deploy.sh
#
# Sourced (not executed) by deploy.sh. Reads deployment settings from
# environment variables with sensible defaults and validates required values.
#
# Environment variables (set these before running deploy.sh):
#
#   WATCH_WAREHOUSE_ID       (required)  SQL Warehouse ID for system.* queries
#   WATCH_APP_NAME           (optional)  Databricks App name          [default: genie-watch]
#   WATCH_DEPLOY_PROFILE     (optional)  Databricks CLI profile       [default: DEFAULT]
#   WATCH_LAKEBASE_INSTANCE  (optional)  Lakebase project name        [default: none]
#   WATCH_DASHBOARD_COST_ID  (optional)  Cost Explorer dashboard ID   [default: none]
#
# After sourcing, the following variables are available:
#   APP_NAME, WAREHOUSE_ID, PROFILE, LAKEBASE_INSTANCE, DASHBOARD_COST_ID
# ---------------------------------------------------------------------------

# ── Load .env.deploy if present (in project root) ─────────────────────────
_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_DEPLOY_ENV="$_PROJECT_DIR/.env.deploy"
if [ -f "$_DEPLOY_ENV" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$_DEPLOY_ENV"
    set +a
fi

# ── Resolve config from env vars ─────────────────────────────────────────
APP_NAME="${WATCH_APP_NAME:-genie-watch}"
WAREHOUSE_ID="${WATCH_WAREHOUSE_ID:-}"
PROFILE="${WATCH_DEPLOY_PROFILE:-DEFAULT}"
LAKEBASE_INSTANCE="${WATCH_LAKEBASE_INSTANCE:-}"
DASHBOARD_COST_ID="${WATCH_DASHBOARD_COST_ID:-}"

# ── Validate required values ─────────────────────────────────────────────
if [ -z "$WAREHOUSE_ID" ]; then
    echo "ERROR: WATCH_WAREHOUSE_ID is required but not set." >&2
    echo "" >&2
    echo "Set it as an environment variable:" >&2
    echo "  export WATCH_WAREHOUSE_ID=<your-sql-warehouse-id>" >&2
    echo "" >&2
    echo "Or create a .env.deploy file in the project root." >&2
    exit 1
fi

# ── Print config summary ─────────────────────────────────────────────────
_print_config() {
    echo "  ┌─ Configuration ─────────────────────────────────────────┐"
    echo "  │  Profile:      $PROFILE"
    echo "  │  App name:     $APP_NAME"
    echo "  │  Warehouse ID: $WAREHOUSE_ID"
    echo "  │  Lakebase:     ${LAKEBASE_INSTANCE:-<none>}"
    echo "  │  Cost dash:    ${DASHBOARD_COST_ID:-<none>}"
    echo "  └─────────────────────────────────────────────────────────┘"
}
