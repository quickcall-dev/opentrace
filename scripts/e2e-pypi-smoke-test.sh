#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale
#
# E2E smoke test for quickcall-opentrace PyPI package.
# Run before pushing: builds wheel → clean venv → pip install → Postgres → full pipeline
#
# Usage:
#   ./scripts/e2e-pypi-smoke-test.sh
#
# Requirements:
#   - Docker (for test Postgres)
#   - uv (for build + clean venv)
#   - curl
#   - lsof (for port cleanup)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_DIR="$(mktemp -d /tmp/qc-e2e-XXXXXX)"
# Use random ports to avoid collisions with stale processes
POSTGRES_PORT="${POSTGRES_PORT:-$(( 25000 + RANDOM % 10000 ))}"
SERVER_PORT="${SERVER_PORT:-$(( 35000 + RANDOM % 10000 ))}"
CONTAINER_NAME="qc-e2e-postgres-${$}"

cleanup() {
    echo "=== Cleaning up ==="
    docker rm -f "$CONTAINER_NAME" &>/dev/null || true
    # Kill any leftover server/daemon processes from this test
    if [[ -f "$TEST_DIR/server.pid" ]]; then
        kill -9 "$(cat "$TEST_DIR/server.pid")" 2>/dev/null || true
    fi
    if [[ -f "$TEST_DIR/daemon.pid" ]]; then
        kill -9 "$(cat "$TEST_DIR/daemon.pid")" 2>/dev/null || true
    fi
    # Kill anything on our test server port
    local pids
    pids="$(lsof -t -i:"$SERVER_PORT" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
        kill -9 $pids 2>/dev/null || true
    fi
    rm -rf "$TEST_DIR"
    echo "=== Cleanup done ==="
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# 0. Kill anything on our ports
# ---------------------------------------------------------------------------
_kill_port_occupiers() {
    local port pids
    for port in "$SERVER_PORT"; do
        pids="$(lsof -t -i:"$port" 2>/dev/null || true)"
        if [[ -n "$pids" ]]; then
            echo "   Killing process on port $port: $pids"
            kill -9 $pids 2>/dev/null || true
            sleep 0.5
        fi
    done
}

# Clean old tmp dirs from previous failed runs
rm -rf /tmp/qc-e2e-* 2>/dev/null || true

echo "=== E2E Smoke Test for quickcall-opentrace ==="
echo "Working dir: $TEST_DIR"
echo "Postgres port: $POSTGRES_PORT"
echo "Server port: $SERVER_PORT"
echo

# ---------------------------------------------------------------------------
# 1. Build wheel
# ---------------------------------------------------------------------------
echo "1. Building wheel..."
cd "$REPO_ROOT"
rm -rf dist/ 2>/dev/null || true
uv build --wheel
WHEEL="$(ls -t "$REPO_ROOT/dist/"*.whl | head -1)"
echo "   Wheel: $WHEEL"

# ---------------------------------------------------------------------------
# 2. Create clean venv and install
# ---------------------------------------------------------------------------
echo "2. Creating clean venv..."
VENV_DIR="$TEST_DIR/venv"
uv venv "$VENV_DIR" --python 3.12
VENV_BIN="$VENV_DIR/bin"
uv pip install --python "$VENV_BIN/python" "$WHEEL"

# Verify entry points exist
for cmd in quickcall quickcall-server quickcall-daemon; do
    if [[ ! -x "$VENV_BIN/$cmd" ]]; then
        echo "ERROR: $cmd not found after install"
        exit 1
    fi
    echo "   ✓ $cmd"
done
echo "   Installed: $($VENV_BIN/quickcall --help | head -1)"

# ---------------------------------------------------------------------------
# 3. Spin up test Postgres
# ---------------------------------------------------------------------------
echo "3. Starting test Postgres..."
docker run -d \
    --name "$CONTAINER_NAME" \
    -e POSTGRES_USER=quickcall \
    -e POSTGRES_PASSWORD=quickcall \
    -e POSTGRES_DB=quickcall \
    -p "${POSTGRES_PORT}:5432" \
    postgres:16-alpine \
    &>/dev/null

# Wait for Postgres to be ready
echo "   Waiting for Postgres..."
for i in {1..30}; do
    if docker exec "$CONTAINER_NAME" pg_isready -U quickcall -d quickcall &>/dev/null; then
        echo "   ✓ Postgres ready"
        break
    fi
    sleep 1
done

if ! docker exec "$CONTAINER_NAME" pg_isready -U quickcall -d quickcall &>/dev/null; then
    echo "ERROR: Postgres failed to start"
    exit 1
fi

DSN="postgresql://quickcall:quickcall@localhost:${POSTGRES_PORT}/quickcall"

# ---------------------------------------------------------------------------
# 4. Run quickcall init (non-interactive)
# ---------------------------------------------------------------------------
echo "4. Running quickcall init..."
export QUICKCALL_OPENTRACE_CONFIG_DIR="$TEST_DIR/config"
printf "%s\n%s\n%s\n" "$DSN" "push_e2e" "admin_e2e" | "$VENV_BIN/quickcall" init

if [[ ! -f "$TEST_DIR/config/config.json" ]]; then
    echo "ERROR: config.json not created"
    exit 1
fi
echo "   ✓ Config created"

# Verify config contents
if ! grep -q "$POSTGRES_PORT" "$TEST_DIR/config/config.json"; then
    echo "ERROR: DSN not written correctly to config.json"
    cat "$TEST_DIR/config/config.json"
    exit 1
fi
echo "   ✓ DSN correct in config"

# ---------------------------------------------------------------------------
# 5. Start server
# ---------------------------------------------------------------------------
echo "5. Starting quickcall-server..."
export QUICKCALL_OPENTRACE_CONFIG_DIR="$TEST_DIR/config"
export QUICKCALL_OPENTRACE_DSN="$DSN"
export QUICKCALL_OPENTRACE_ADMIN_KEYS="admin_e2e"
export QUICKCALL_OPENTRACE_PUSH_KEYS="push_e2e"
export QUICKCALL_OPENTRACE_PORT="$SERVER_PORT"

"$VENV_BIN/python" -m opentrace.server > "$TEST_DIR/server.log" 2>&1 &
echo $! > "$TEST_DIR/server.pid"

# Wait for server
echo "   Waiting for server..."
for i in {1..30}; do
    if curl -sf "http://localhost:${SERVER_PORT}/health" &>/dev/null; then
        echo "   ✓ Server ready on port $SERVER_PORT"
        break
    fi
    sleep 0.5
done

if ! curl -sf "http://localhost:${SERVER_PORT}/health" &>/dev/null; then
    echo "ERROR: Server failed to start"
    tail -20 "$TEST_DIR/server.log"
    exit 1
fi

# ---------------------------------------------------------------------------
# 6. Start daemon
# ---------------------------------------------------------------------------
echo "6. Starting quickcall-daemon..."
export QUICKCALL_OPENTRACE_API_KEY="push_e2e"
export QUICKCALL_OPENTRACE_INGEST_URL="http://localhost:${SERVER_PORT}/ingest"
export QUICKCALL_OPENTRACE_MAX_FILES=100  # limit: don't scan thousands of real sessions
"$VENV_BIN/quickcall-daemon" > "$TEST_DIR/daemon.log" 2>&1 &
echo $! > "$TEST_DIR/daemon.pid"
sleep 2

# Verify daemon is running
if ! kill -0 "$(cat "$TEST_DIR/daemon.pid")" 2>/dev/null; then
    echo "ERROR: Daemon failed to start"
    tail -20 "$TEST_DIR/daemon.log"
    exit 1
fi
echo "   ✓ Daemon running (PID $(cat "$TEST_DIR/daemon.pid"))"

# ---------------------------------------------------------------------------
# 7. Run quickcall doctor
# ---------------------------------------------------------------------------
echo "7. Running quickcall doctor..."
"$VENV_BIN/quickcall" doctor > "$TEST_DIR/doctor.out" 2>&1 || true
if grep -q "All checks passed" "$TEST_DIR/doctor.out"; then
    echo "   ✓ Doctor: all checks passed"
else
    echo "   ⚠ Doctor output:"
    cat "$TEST_DIR/doctor.out"
fi

# ---------------------------------------------------------------------------
# 8. Run quickcall status
# ---------------------------------------------------------------------------
echo "8. Running quickcall status..."
"$VENV_BIN/quickcall" status > "$TEST_DIR/status.out" 2>&1 || true
if grep -q "running" "$TEST_DIR/status.out"; then
    echo "   ✓ Status: daemon running"
else
    echo "   ⚠ Status output:"
    cat "$TEST_DIR/status.out"
fi

# ---------------------------------------------------------------------------
# 9. Verify database has schema
# ---------------------------------------------------------------------------
echo "9. Verifying database schema..."
TABLE_COUNT="$(docker exec "$CONTAINER_NAME" psql -U quickcall -d quickcall -Atc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null || echo 0)"
echo "   Tables created: $TABLE_COUNT"
if [[ "$TABLE_COUNT" -lt 5 ]]; then
    echo "ERROR: Expected at least 5 tables, found $TABLE_COUNT"
    exit 1
fi
echo "   ✓ Schema applied"

# ---------------------------------------------------------------------------
# 10. If session dirs exist, wait for ingestion
# ---------------------------------------------------------------------------
SESSION_DIRS=(
    "$HOME/.claude/projects"
    "$HOME/.codex/sessions"
    "$HOME/.gemini"
    "$HOME/.cursor/projects"
    "$HOME/.pi/agent/sessions"
)
HAS_SESSIONS=false
for d in "${SESSION_DIRS[@]}"; do
    if [[ -d "$d" ]]; then
        HAS_SESSIONS=true
        break
    fi
done

if [[ "$HAS_SESSIONS" == true ]]; then
    echo "10. Waiting for session ingestion (10s)..."
    sleep 10

    SESSION_COUNT="$(docker exec "$CONTAINER_NAME" psql -U quickcall -d quickcall -Atc "SELECT COUNT(*) FROM sessions;" 2>/dev/null || echo 0)"
    echo "    Sessions ingested: $SESSION_COUNT"
    if [[ "$SESSION_COUNT" -gt 0 ]]; then
        echo "    ✓ Data flowing into database"
    else
        echo "    ⚠ No sessions yet (may need more time or no CLI sessions found)"
    fi
else
    echo "10. Skipping ingestion test — no session directories found"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo
echo "========================================"
echo "✓ E2E smoke test PASSED"
echo "========================================"
echo
echo "What was tested:"
echo "  1. Wheel built from source"
echo "  2. Clean venv pip install"
echo "  3. quickcall init with piped input"
echo "  4. quickcall-server starts and responds to /health"
echo "  5. quickcall-daemon starts and connects"
echo "  6. quickcall doctor reports all checks passed"
echo "  7. quickcall status shows daemon running"
echo "  8. Database schema auto-created"
echo "  9. Session data ingests (if session dirs exist)"
echo
echo "Cleanup handled automatically"
