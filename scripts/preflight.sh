#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# preflight.sh — reusable pre-flight validation functions for deploy.sh
# ---------------------------------------------------------------------------

_preflight_check_tools() {
    echo "  Checking required tools..."
    local missing=()
    command -v databricks &>/dev/null || missing+=("databricks")
    command -v python3 &>/dev/null    || missing+=("python3")
    command -v node &>/dev/null       || missing+=("node")
    command -v npm &>/dev/null        || missing+=("npm")
    command -v uv &>/dev/null         || missing+=("uv")
    if [ ${#missing[@]} -gt 0 ]; then
        echo ""
        echo "  ✗ Missing required tools: ${missing[*]}"
        if [[ " ${missing[*]} " == *" uv "* ]]; then
            echo "  Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
        fi
        exit 1
    fi
    echo "  ✓ All required tools available (databricks, python3, node, npm, uv)"

    local node_version
    node_version=$(node --version 2>/dev/null || echo "unknown")
    if ! node -e '
const [major, minor] = process.versions.node.split(".").map(Number);
const supported = (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22;
process.exit(supported ? 0 : 1);
'; then
        echo ""
        echo "  ✗ Node.js $node_version is not supported (need ^20.19.0 or >=22.12.0)."
        exit 1
    fi
    echo "  ✓ Node.js version $node_version"

    local cli_version min_cli_version="0.297.2"
    cli_version=$(databricks --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
    if [ -n "$cli_version" ]; then
        local lowest
        lowest=$(printf '%s\n%s\n' "$min_cli_version" "$cli_version" | sort -V | head -1)
        if [ "$lowest" != "$min_cli_version" ]; then
            echo "  ✗ Databricks CLI $cli_version too old (need >= $min_cli_version)"
            exit 1
        fi
        echo "  ✓ Databricks CLI version $cli_version"
    fi
}

_preflight_check_venv() {
    echo "  Syncing Python venv (uv sync --frozen)..."
    if uv sync --frozen --quiet 2>/dev/null; then
        echo "  ✓ Python venv ready (pinned dependencies)"
    elif uv sync --quiet; then
        echo "  ✓ Python venv ready (no lock file yet — generated)"
    else
        echo "  ✗ uv sync failed."
        exit 1
    fi
}

_preflight_check_profile() {
    local profile="$1"
    echo "  Checking CLI profile '$profile'..."
    if ! databricks current-user me --profile "$profile" -o json &>/dev/null; then
        echo ""
        echo "  ✗ Cannot authenticate with profile '$profile'."
        echo "  Run: databricks configure --profile $profile"
        exit 1
    fi
    echo "  ✓ CLI profile is valid"
}

_preflight_check_warehouse() {
    local warehouse_id="$1"
    local profile="$2"
    echo "  Checking SQL warehouse '$warehouse_id'..."
    local wh_output
    if ! wh_output=$(databricks warehouses get "$warehouse_id" --profile "$profile" -o json 2>&1); then
        echo "  ✗ SQL warehouse '$warehouse_id' is not accessible."
        echo "  List warehouses: databricks warehouses list --profile $profile"
        exit 1
    fi
    local wh_state
    wh_state=$(echo "$wh_output" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state','UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")
    echo "  ✓ SQL warehouse exists (state: $wh_state)"
}

_preflight_check_app_state() {
    local app_name="$1"
    local profile="$2"
    echo "  Checking app state for '$app_name'..."
    local app_output
    if app_output=$(databricks apps get "$app_name" --profile "$profile" -o json 2>/dev/null); then
        local app_status
        app_status=$(echo "$app_output" | python3 -c "
import sys, json
d = json.load(sys.stdin)
status = d.get('status', {}).get('state', d.get('compute_status', {}).get('state', 'UNKNOWN'))
print(status)
" 2>/dev/null || echo "UNKNOWN")
        if echo "$app_status" | grep -qi "delet\|cleanup"; then
            echo "  ⚠ App '$app_name' is in '$app_status' state — wait for cleanup."
            exit 1
        fi
        echo "  ✓ App exists (state: $app_status)"
    else
        echo "  ✓ App does not exist yet — deploy will create it"
    fi
}
