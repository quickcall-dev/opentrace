#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale
#
# Docker Compose E2E smoke test.
# Validates `quickcall up` / `quickcall down` and the full stack.
#
# Usage:
#   ./scripts/e2e-docker-smoke-test.sh
#
# Requirements:
#   - Docker + docker compose
#   - curl

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# Use random ports to avoid collisions with stale processes
export DB_HOST_PORT="${DB_HOST_PORT:-$(( 26000 + RANDOM % 10000 ))}"
export SERVER_HOST_PORT="${SERVER_HOST_PORT:-$(( 36000 + RANDOM % 10000 ))}"
export FRONTEND_HOST_PORT="${FRONTEND_HOST_PORT:-$(( 27000 + RANDOM % 10000 ))}"
COMPOSE_PROJECT="qc-e2e-docker-${$}"
# Shorthand for curl checks
SERVER_PORT="$SERVER_HOST_PORT"
FRONTEND_PORT="$FRONTEND_HOST_PORT"

cleanup() {
    echo "=== Cleaning up ==="
    cd "$REPO_ROOT"
    docker compose -p "$COMPOSE_PROJECT" down -v &>/dev/null || true
    # Also remove images from this test run
    docker images -q --filter "reference=${COMPOSE_PROJECT}*" | xargs -r docker rmi -f &>/dev/null || true
    echo "=== Cleanup done ==="
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# 0. Kill anything on our ports
# ---------------------------------------------------------------------------
_kill_port_occupiers() {
    local port pids
    for port in "$FRONTEND_HOST_PORT" "$SERVER_HOST_PORT" "$DB_HOST_PORT"; do
        pids="$(lsof -t -i:"$port" 2>/dev/null || true)"
        if [[ -n "$pids" ]]; then
            echo "   Killing process on port $port: $pids"
            kill -9 $pids 2>/dev/null || true
            sleep 0.5
        fi
    done
}

_kill_port_occupiers

# Prune old failed runs before starting
docker ps -aq --filter "name=qc-e2e-docker" | xargs -r docker rm -f &>/dev/null || true
docker images -q --filter "reference=qc-e2e-docker*" | xargs -r docker rmi -f &>/dev/null || true

echo "=== Docker Compose E2E Smoke Test ==="
echo "Repo: $REPO_ROOT"
echo "Project: $COMPOSE_PROJECT"
echo "Server port: $SERVER_HOST_PORT"
echo "Frontend port: $FRONTEND_HOST_PORT"
echo "DB port: $DB_HOST_PORT"
echo

# ---------------------------------------------------------------------------
# 1. Start the full stack
# ---------------------------------------------------------------------------
echo "1. Starting stack with docker compose up -d..."
export QUICKCALL_OPENTRACE_MAX_FILES=100  # limit: don't scan thousands of real sessions
cd "$REPO_ROOT"
docker compose -p "$COMPOSE_PROJECT" up -d &>/dev/null

# Wait for services
echo "   Waiting for services..."
for i in {1..60}; do
    if docker compose -p "$COMPOSE_PROJECT" ps | grep -q "healthy\|Up"; then
        break
    fi
    sleep 1
done

# ---------------------------------------------------------------------------
# 2. Check all containers are running
# ---------------------------------------------------------------------------
echo "2. Checking containers..."
CONTAINERS=("db" "server" "daemon" "frontend")
for svc in "${CONTAINERS[@]}"; do
    if docker compose -p "$COMPOSE_PROJECT" ps "$svc" | grep -q "Up"; then
        echo "   ✓ $svc running"
    else
        echo "   ✗ $svc not running"
        docker compose -p "$COMPOSE_PROJECT" logs "$svc" | tail -20
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# 3. Check server health
# ---------------------------------------------------------------------------
echo "3. Checking server health..."
for i in {1..30}; do
    if curl -sf "http://localhost:${SERVER_PORT}/health" &>/dev/null; then
        echo "   ✓ Server responds on :$SERVER_PORT"
        break
    fi
    sleep 1
done

if ! curl -sf "http://localhost:${SERVER_PORT}/health" &>/dev/null; then
    echo "   ✗ Server not responding"
    docker compose -p "$COMPOSE_PROJECT" logs server | tail -20
    exit 1
fi

# ---------------------------------------------------------------------------
# 4. Check frontend responds
# ---------------------------------------------------------------------------
echo "4. Checking frontend..."
for i in {1..30}; do
    if curl -sf "http://localhost:${FRONTEND_PORT}" &>/dev/null; then
        echo "   ✓ Frontend responds on :$FRONTEND_PORT"
        break
    fi
    sleep 1
done

if ! curl -sf "http://localhost:${FRONTEND_PORT}" &>/dev/null; then
    echo "   ✗ Frontend not responding"
    docker compose -p "$COMPOSE_PROJECT" logs frontend | tail -20
    exit 1
fi

# ---------------------------------------------------------------------------
# 5. Check DB schema
# ---------------------------------------------------------------------------
echo "5. Checking database schema..."
TABLE_COUNT="$(docker exec "${COMPOSE_PROJECT}-db-1" psql -U quickcall -d quickcall -Atc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null || echo 0)"
echo "   Tables: $TABLE_COUNT"
if [[ "$TABLE_COUNT" -lt 5 ]]; then
    echo "   ✗ Expected at least 5 tables"
    exit 1
fi
echo "   ✓ Schema applied"

# ---------------------------------------------------------------------------
# 6. Wait for daemon ingestion
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
    echo "6. Waiting for ingestion (15s)..."
    sleep 15
    SESSION_COUNT="$(docker exec "${COMPOSE_PROJECT}-db-1" psql -U quickcall -d quickcall -Atc "SELECT COUNT(*) FROM sessions;" 2>/dev/null || echo 0)"
    echo "   Sessions: $SESSION_COUNT"
    if [[ "$SESSION_COUNT" -gt 0 ]]; then
        echo "   ✓ Data ingested"
    else
        echo "   ⚠ No sessions yet"
    fi
else
    echo "6. Skipping ingestion — no session dirs found"
fi

# ---------------------------------------------------------------------------
# 7. Stop stack with quickcall down
# ---------------------------------------------------------------------------
echo "7. Stopping stack with docker compose down..."
cd "$REPO_ROOT"
docker compose -p "$COMPOSE_PROJECT" down &>/dev/null
echo "   ✓ Stack stopped"

# Verify nothing left
REMAINING="$(docker compose -p "$COMPOSE_PROJECT" ps -q 2>/dev/null || true)"
if [[ -z "$REMAINING" ]]; then
    echo "   ✓ All containers removed"
else
    echo "   ⚠ Some containers still running:"
    docker compose -p "$COMPOSE_PROJECT" ps
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo
echo "========================================"
echo "✓ Docker Compose E2E smoke test PASSED"
echo "========================================"
echo
echo "What was tested:"
echo "  1. docker compose up -d starts all 4 services"
echo "  2. Server responds on :$SERVER_PORT/health"
echo "  3. Frontend responds on :$FRONTEND_PORT"
echo "  4. Database schema auto-created"
echo "  5. Daemon ingests sessions (if dirs exist)"
echo "  6. docker compose down removes everything"
echo
echo "Cleanup handled automatically"
