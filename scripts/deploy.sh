#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# deploy.sh — deploy GenieWatch to Databricks Apps.
#
# Three modes:
#   Full deploy (default): preflight, build, create app, sync, configure, deploy
#   Update mode (--update): code-only update; skips app creation
#   Destroy mode (--destroy): delete the app
#
# GenieWatch has no bundle-managed jobs — this script is simpler than
# genie-workbench's deploy.sh because there's no GSO wheel to build or
# job DAG to deploy.
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

UPDATE_ONLY=false
DESTROY_MODE=false
AUTO_APPROVE=false
for arg in "$@"; do
    case "$arg" in
        --update)       UPDATE_ONLY=true ;;
        --destroy)      DESTROY_MODE=true ;;
        --auto-approve) AUTO_APPROVE=true ;;
    esac
done

# shellcheck source=deploy-config.sh
source "$SCRIPT_DIR/deploy-config.sh"
# shellcheck source=preflight.sh
source "$SCRIPT_DIR/preflight.sh"

# ═══════════════════════════════════════════════════════════════════════════
# DESTROY MODE
# ═══════════════════════════════════════════════════════════════════════════
if [ "$DESTROY_MODE" = "true" ]; then
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  GenieWatch — Destroy                                        ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    _print_config

    if [ "$AUTO_APPROVE" != "true" ]; then
        echo ""
        echo "  This will permanently delete the app '$APP_NAME'."
        echo "  Lakebase data, MLflow experiments, and user-set mappings are NOT removed."
        echo -n "  Continue? [y/N]: "
        read -r confirm
        if [[ ! "$confirm" =~ ^[Yy] ]]; then
            echo "  Cancelled."
            exit 0
        fi
    fi

    if databricks apps get "$APP_NAME" --profile "$PROFILE" &>/dev/null; then
        databricks apps delete "$APP_NAME" --profile "$PROFILE"
        echo "  ✓ App '$APP_NAME' deleted"
    else
        echo "  App '$APP_NAME' does not exist — nothing to delete."
    fi
    exit 0
fi

# ═══════════════════════════════════════════════════════════════════════════
# DEPLOY / UPDATE MODE
# ═══════════════════════════════════════════════════════════════════════════
if [ "$UPDATE_ONLY" = "true" ]; then
    TOTAL_STEPS=7
    DEPLOY_LABEL="Code Update"
else
    TOTAL_STEPS=8
    DEPLOY_LABEL="Full Deploy"
fi

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  GenieWatch — $DEPLOY_LABEL$(printf '%*s' $((48 - ${#DEPLOY_LABEL})) '')║"
echo "╚══════════════════════════════════════════════════════════════╝"
_print_config

# ── Step 1: Pre-flight ────────────────────────────────────────────────────
echo ""
echo "▸ Step 1/$TOTAL_STEPS: Pre-flight checks..."
_preflight_check_tools
_preflight_check_venv
_preflight_check_profile "$PROFILE"

DEPLOYER=$(databricks current-user me --profile "$PROFILE" -o json \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['userName'])")
WS_PATH="/Workspace/Users/$DEPLOYER/$APP_NAME"

_preflight_check_warehouse "$WAREHOUSE_ID" "$PROFILE"
_preflight_check_app_state "$APP_NAME" "$PROFILE"
echo "  ✓ All pre-flight checks passed"

# ── Step 2: Build frontend ────────────────────────────────────────────────
echo ""
echo "▸ Step 2/$TOTAL_STEPS: Building frontend..."
if ! (cd "$PROJECT_DIR/frontend" && npm ci && npm run build); then
    echo "  ✗ Frontend build failed."
    exit 1
fi
if [ ! -f "$PROJECT_DIR/frontend/dist/index.html" ]; then
    echo "  ✗ frontend/dist/index.html not found after build."
    exit 1
fi
echo "  ✓ Frontend built"

STEP=2

if [ "$UPDATE_ONLY" != "true" ]; then
    # ── Step 3 (full): Create app if not exists ───────────────────────────
    STEP=$((STEP + 1))
    echo ""
    echo "▸ Step $STEP/$TOTAL_STEPS: Creating app (if not exists)..."
    if databricks apps get "$APP_NAME" --profile "$PROFILE" &>/dev/null; then
        echo "  ✓ App '$APP_NAME' already exists"
    else
        APP_CREATE_JSON=$(python3 -c "import json; print(json.dumps({'name': '$APP_NAME', 'description': 'GenieWatch — observability for Genie Spaces'}))")
        databricks apps create --json "$APP_CREATE_JSON" --profile "$PROFILE" --no-wait
        echo "  ✓ App created (compute starting in background)"
    fi
fi

# ── Sync to workspace ─────────────────────────────────────────────────────
STEP=$((STEP + 1))
echo ""
echo "▸ Step $STEP/$TOTAL_STEPS: Syncing files to workspace..."
echo "  Cleaning stale workspace files..."
databricks workspace delete "$WS_PATH" --profile "$PROFILE" --recursive 2>/dev/null || true
databricks sync "$PROJECT_DIR" "$WS_PATH" --profile "$PROFILE" --full \
    --exclude-from "$PROJECT_DIR/.databricksignore"
echo "  Uploading frontend build artifacts..."
databricks workspace import-dir "$PROJECT_DIR/frontend/dist" \
    "$WS_PATH/frontend/dist" --profile "$PROFILE" --overwrite
echo "  ✓ Files synced to $WS_PATH"

# ── Resolve SP + grant permissions ────────────────────────────────────────
STEP=$((STEP + 1))
echo ""
echo "▸ Step $STEP/$TOTAL_STEPS: Resolving app SP and granting permissions..."
SP_CLIENT_ID=$(
    databricks apps get "$APP_NAME" --profile "$PROFILE" -o json \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('service_principal_client_id','') or d.get('service_principal_name',''))"
)
if [ -z "$SP_CLIENT_ID" ]; then
    echo "  ✗ Could not resolve SP for app '$APP_NAME'."
    exit 1
fi
echo "  ✓ SP client ID: $SP_CLIENT_ID"

# Grant system table SELECTs to the app SP. Best-effort — if the deployer
# isn't a workspace admin, these will fail and the user must run them by hand.
uv run python "$SCRIPT_DIR/grant_permissions.py" \
    --profile "$PROFILE" \
    --sp-client-id "$SP_CLIENT_ID" \
    --warehouse-id "$WAREHOUSE_ID" || \
    echo "  ⚠ Some grants failed — see docs/system-tables-grants.md to apply manually."

# ── Set up Lakebase (optional) ────────────────────────────────────────────
if [ -n "$LAKEBASE_INSTANCE" ] && [ -n "$SP_CLIENT_ID" ]; then
    echo ""
    echo "  Setting up Lakebase Autoscaling..."
    uv run python "$SCRIPT_DIR/setup_lakebase.py" \
        --profile "$PROFILE" \
        --project-name "$LAKEBASE_INSTANCE" \
        --sp-client-id "$SP_CLIENT_ID" 2>&1 || \
        echo "  ⚠ Lakebase setup had errors — app will fall back to in-memory storage"
fi

# ── Bundle deploy (creates / updates the executive overview dashboard) ───
STEP=$((STEP + 1))
echo ""
echo "▸ Step $STEP/$TOTAL_STEPS: Deploying DAB resources (Lakeview dashboard)..."
rm -f "$PROJECT_DIR/.databricks/bundle/app/sync-snapshots/"*.json 2>/dev/null || true
set +e
BUNDLE_OUTPUT=$(cd "$PROJECT_DIR" && databricks bundle deploy -t app \
    --var="warehouse_id=$WAREHOUSE_ID" \
    --profile "$PROFILE" 2>&1)
BUNDLE_EXIT=$?
set -e
echo "$BUNDLE_OUTPUT" | sed 's/^/  /'
if [ "$BUNDLE_EXIT" -ne 0 ]; then
    echo "  ⚠ Bundle deploy failed — dashboard may not be created. App will still deploy."
    DASHBOARD_COST_ID=""
else
    DASHBOARD_COST_ID=$(cd "$PROJECT_DIR" && databricks bundle summary -t app \
        --var="warehouse_id=$WAREHOUSE_ID" \
        --profile "$PROFILE" -o json 2>/dev/null \
        | python3 -c "
import sys, json
try:
    s = json.load(sys.stdin)
    print(s['resources']['dashboards']['genie_spaces_overview']['id'])
except Exception:
    pass
" 2>/dev/null || true)
    if [ -n "$DASHBOARD_COST_ID" ]; then
        echo "  ✓ Dashboard ID: $DASHBOARD_COST_ID"
    else
        echo "  ⚠ Dashboard deployed but ID not resolved from bundle state."
    fi
fi

# ── Grant the app SP CAN_RUN on the dashboard ─────────────────────────────
# Required for the embed-token mint flow (see backend/services/embed_tokens.py).
# CAN_RUN lets the SP execute the dashboard against the warehouse on behalf
# of the embedding viewer. CAN_READ is not enough — the OIDC scoped-token
# request rejects authorization_details for a principal that only has read.
if [ -n "$DASHBOARD_COST_ID" ] && [ -n "$SP_CLIENT_ID" ]; then
    echo ""
    echo "  Granting SP CAN_RUN on dashboard for embed-token mint..."
    databricks api patch "/api/2.0/permissions/dashboards/$DASHBOARD_COST_ID" \
        --profile "$PROFILE" \
        --json "{\"access_control_list\":[{\"service_principal_name\":\"$SP_CLIENT_ID\",\"permission_level\":\"CAN_RUN\"}]}" \
        >/dev/null 2>&1 \
        && echo "  ✓ Dashboard CAN_RUN granted to SP" \
        || echo "  ⚠ Could not grant dashboard CAN_RUN — embed will fail until the SP has run access."
fi

# ── Resolve Lakebase database ID ──────────────────────────────────────────
LAKEBASE_DB_RESOURCE=""
if [ -n "$LAKEBASE_INSTANCE" ]; then
    LAKEBASE_DB_RESOURCE=$(databricks api get "/api/2.0/postgres/projects/$LAKEBASE_INSTANCE/branches/production/databases" \
        --profile "$PROFILE" -o json 2>/dev/null \
        | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    dbs = data.get('databases', [])
    if dbs:
        print(dbs[0]['name'])
except Exception: pass
" 2>/dev/null || true)
fi

# ── Patch app.yaml on workspace ───────────────────────────────────────────
STEP=$((STEP + 1))
echo ""
echo "▸ Step $STEP/$TOTAL_STEPS: Patching app.yaml on workspace..."
PATCHED_APP_YAML="/tmp/app.yaml.patched"
cp "$PROJECT_DIR/app.yaml" "$PATCHED_APP_YAML"
sed -i.bak "s|__WAREHOUSE_ID__|$WAREHOUSE_ID|g" "$PATCHED_APP_YAML"
sed -i.bak "s|__LAKEBASE_INSTANCE__|$LAKEBASE_INSTANCE|g" "$PATCHED_APP_YAML"
sed -i.bak "s|__DASHBOARD_COST_ID__|$DASHBOARD_COST_ID|g" "$PATCHED_APP_YAML"
rm -f "${PATCHED_APP_YAML}.bak"

UNRESOLVED=$(grep -c '__[A-Z_]*__' "$PATCHED_APP_YAML" || true)
if [ "$UNRESOLVED" -gt 0 ]; then
    echo "  ⚠ app.yaml has $UNRESOLVED unresolved placeholder(s):"
    grep '__[A-Z_]*__' "$PATCHED_APP_YAML" | sed 's/^/      /'
fi

databricks workspace import "$WS_PATH/app.yaml" \
    --profile "$PROFILE" --file "$PATCHED_APP_YAML" --format AUTO --overwrite
echo "  ✓ app.yaml patched"

# ── Configure app scopes and resources ────────────────────────────────────
echo ""
echo "  Configuring app scopes and resources..."
EXISTING_RESOURCES=$(databricks apps get "$APP_NAME" --profile "$PROFILE" -o json 2>/dev/null \
    | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('resources',[])))" 2>/dev/null || echo "[]")

PATCH_PAYLOAD=$(python3 -c "
import json
scopes = ['sql', 'dashboards.genie',
          'catalog.catalogs:read', 'catalog.schemas:read', 'catalog.tables:read']
existing = json.loads('$EXISTING_RESOURCES')
app_yaml_resources = {'sql-warehouse', 'postgres'}
by_name = {}
for r in existing:
    has_config = any(k for k in r if k != 'name')
    if has_config or r.get('name') in app_yaml_resources:
        by_name[r['name']] = r
by_name['sql-warehouse'] = {'name': 'sql-warehouse', 'sql_warehouse': {'id': '$WAREHOUSE_ID', 'permission': 'CAN_USE'}}

lakebase_db = '$LAKEBASE_DB_RESOURCE'
if lakebase_db:
    branch = '/'.join(lakebase_db.split('/')[:4])
    by_name['postgres'] = {'name': 'postgres', 'postgres': {
        'branch': branch,
        'database': lakebase_db,
        'permission': 'CAN_CONNECT_AND_CREATE',
    }}

print(json.dumps({'user_api_scopes': scopes, 'resources': list(by_name.values())}))
")
if databricks api patch "/api/2.0/apps/$APP_NAME" \
        --profile "$PROFILE" --json "$PATCH_PAYLOAD"; then
    echo "  ✓ App scopes and resources configured"
else
    echo "  ⚠ Could not configure app scopes/resources (see error above)"
fi

# ── Deploy app ────────────────────────────────────────────────────────────
STEP=$((STEP + 1))
echo ""
echo "▸ Step $STEP/$TOTAL_STEPS: Deploying app..."
APP_STATE=$(databricks apps get "$APP_NAME" --profile "$PROFILE" -o json \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('compute_status',{}).get('state','UNKNOWN'))")
if [ "$APP_STATE" != "ACTIVE" ]; then
    echo "  ℹ App compute is $APP_STATE — starting..."
    databricks apps start "$APP_NAME" --profile "$PROFILE" --no-wait 2>/dev/null || true
    for i in $(seq 1 30); do
        sleep 10
        APP_STATE=$(databricks apps get "$APP_NAME" --profile "$PROFILE" -o json \
            | python3 -c "import sys,json; print(json.load(sys.stdin).get('compute_status',{}).get('state','UNKNOWN'))")
        if [ "$APP_STATE" = "ACTIVE" ]; then break; fi
        echo "    ... $APP_STATE (attempt $i/30)"
    done
fi
databricks apps deploy "$APP_NAME" --profile "$PROFILE" \
    --source-code-path "$WS_PATH" --no-wait
echo "  ✓ App deployment triggered"

# ── Verify ────────────────────────────────────────────────────────────────
STEP=$((STEP + 1))
echo ""
echo "▸ Step $STEP/$TOTAL_STEPS: Verifying deployment..."
DEPLOY_STATE="IN_PROGRESS"
for i in $(seq 1 18); do
    sleep 10
    APP_JSON=$(databricks apps get "$APP_NAME" --profile "$PROFILE" -o json 2>/dev/null)
    DEPLOY_STATE=$(echo "$APP_JSON" | python3 -c "
import sys,json
d=json.load(sys.stdin)
ad = d.get('pending_deployment',{}) or d.get('active_deployment',{})
print(ad.get('status',{}).get('state','UNKNOWN'))
" 2>/dev/null || echo "UNKNOWN")
    if [ "$DEPLOY_STATE" != "IN_PROGRESS" ]; then break; fi
    echo "    ... $DEPLOY_STATE (attempt $i/18)"
done

APP_URL=$(echo "${APP_JSON:-{}}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('url',''))" 2>/dev/null || true)

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Deploy complete!"
echo "  App:    $APP_NAME"
echo "  SP:     $SP_CLIENT_ID"
echo "  State:  $DEPLOY_STATE"
echo ""
if [ -n "$APP_URL" ]; then
    echo "  URL: $APP_URL"
fi
echo ""
echo "  NOTE: If 'Failed to list spaces' appears, ensure the SP has the"
echo "  system-table grants documented in docs/system-tables-grants.md."
echo "═══════════════════════════════════════════════════════════════"
