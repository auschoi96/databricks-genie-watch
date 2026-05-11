#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# install.sh — guided first-time setup for GenieWatch.
#
# Walks through:
#   1. Tool checks
#   2. Profile selection
#   3. Workspace discovery (warehouses)
#   4. Optional Lakebase project name
#   5. Optional Cost Explorer dashboard ID
#   6. Writes .env.deploy
#   7. Calls deploy.sh to do the actual deploy
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env.deploy"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  GenieWatch — Guided Install                                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Prerequisite: a workspace admin must allow dashboard embedding on the"
echo "app's origin. Settings → Security → Embedding for dashboards →"
echo "approved domains must include 'databricksapps.com' (or your app's"
echo "specific subdomain). The embedded Cost Explorer will not render"
echo "without this, regardless of the embed-token flow."
echo ""

# Tools
for tool in databricks python3 node npm uv; do
    if ! command -v "$tool" &>/dev/null; then
        echo "✗ Required tool missing: $tool"
        echo "  Install instructions in scripts/preflight.sh"
        exit 1
    fi
done
echo "✓ Required tools found"

# Profile
echo ""
read -r -p "Databricks CLI profile [DEFAULT]: " PROFILE
PROFILE="${PROFILE:-DEFAULT}"
if ! databricks current-user me --profile "$PROFILE" -o json &>/dev/null; then
    echo "✗ Profile '$PROFILE' is not authenticated."
    echo "  Run: databricks configure --profile $PROFILE"
    exit 1
fi
USER_NAME=$(databricks current-user me --profile "$PROFILE" -o json \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('userName','?'))")
echo "✓ Authenticated as $USER_NAME on profile '$PROFILE'"

# Warehouse
echo ""
echo "Available SQL warehouses:"
databricks warehouses list --profile "$PROFILE" -o json 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
whs = data if isinstance(data, list) else data.get('warehouses', [])
for w in whs:
    print(f\"  {w.get('id','')}  {w.get('name','')} ({w.get('state','UNKNOWN')})\")
" || true
read -r -p "Warehouse ID: " WAREHOUSE_ID
if [ -z "$WAREHOUSE_ID" ]; then
    echo "✗ Warehouse ID is required."
    exit 1
fi

# App name
echo ""
read -r -p "Databricks App name [genie-watch]: " APP_NAME
APP_NAME="${APP_NAME:-genie-watch}"

# Lakebase
echo ""
read -r -p "Lakebase project name (optional, leave empty to skip): " LAKEBASE_INSTANCE

# The Lakeview dashboard is created by `databricks bundle deploy` (see
# databricks.yml). The deploy script reads its ID from bundle state and
# injects it into app.yaml automatically — no need to prompt.

# Write .env.deploy
cat > "$ENV_FILE" <<EOF
WATCH_DEPLOY_PROFILE=$PROFILE
WATCH_APP_NAME=$APP_NAME
WATCH_WAREHOUSE_ID=$WAREHOUSE_ID
WATCH_LAKEBASE_INSTANCE=$LAKEBASE_INSTANCE
# WATCH_DASHBOARD_COST_ID is auto-resolved from the DAB on deploy.
# Set it explicitly here only to override (e.g. embed a different dashboard).
WATCH_DASHBOARD_COST_ID=
EOF
echo "✓ Wrote $ENV_FILE"

# Deploy
echo ""
echo "Running ./scripts/deploy.sh..."
exec "$SCRIPT_DIR/deploy.sh"
