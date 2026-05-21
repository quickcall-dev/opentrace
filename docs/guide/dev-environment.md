# Development Environment Setup

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | [uv](https://docs.astral.sh/uv/getting-started/installation/) handles this |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | any | [docker.com](https://docs.docker.com/get-docker/) |
| Node.js | 20+ | [nodejs.org](https://nodejs.org/) or `nvm` |

## 1. Clone and install

```bash
git clone https://github.com/quickcall-dev/opentrace.git
cd opentrace
uv sync --extra dev
```

This creates a virtual environment (`.venv/`) and installs all dependencies including dev tools.

## 2. Start PostgreSQL

```bash
docker compose up -d db
```

Or use your own Postgres. Create a database named `quickcall` and set the DSN:

```bash
export QUICKCALL_OPENTRACE_DSN=postgresql://user:pass@localhost:5432/quickcall
```

Schema is applied automatically when the server starts.

## 3. Run the backend

**Terminal 1 — Ingest server:**
```bash
uv run python -m opentrace.server
# → http://localhost:19777
```

**Terminal 2 — Daemon:**
```bash
uv run python -m opentrace.daemon
# Watches ~/.claude, ~/.codex, ~/.gemini, ~/.cursor, ~/.pi
```

Or use the CLI:
```bash
uv run quickcall-daemon run
```

## 4. Run the frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

The frontend proxies API calls to `localhost:19777` in development.

## 5. Run tests

```bash
# All tests (requires Postgres running)
uv run pytest

# Specific module
uv run pytest tests/daemon/

# With coverage
uv run pytest --cov=opentrace
```

### Pre-push E2E smoke tests

Run both before every push to main. They catch issues unit tests miss.

**PyPI package (PyPI / BYOP path):**
```bash
./scripts/e2e-pypi-smoke-test.sh
```

Builds wheel → clean venv → pip install → Postgres → full pipeline → verify DB.

**Docker Compose (full stack path):**
```bash
./scripts/e2e-docker-smoke-test.sh
```

`docker compose up -d` → checks server/frontend/DB → verifies ingestion → `docker compose down`.

Both auto-clean on exit.

## 6. Lint and format

```bash
uv run ruff check opentrace/ tests/
uv run ruff format opentrace/ tests/
```

## 7. Common workflows

### Rebuild Docker after backend changes
```bash
docker compose up -d --build server daemon
```

### Rebuild Docker after frontend changes
```bash
docker compose up -d --build frontend
```

### Wipe DB and re-ingest everything
```bash
PGPASSWORD=quickcall psql -h localhost -p 15433 -U quickcall -d quickcall -c \
  "TRUNCATE TABLE tool_calls, tool_results, token_usage, messages, file_progress, sessions, schema_version RESTART IDENTITY CASCADE; INSERT INTO schema_version (version) VALUES (1);"
rm ~/.quickcall-opentrace/state.json ~/.quickcall-opentrace/backfilled_sessions.json 2>/dev/null
docker compose restart daemon
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `psycopg.OperationalError: connection refused` | Make sure Postgres is running: `docker compose up -d db` |
| Daemon shows "0 files" | Check that session files exist in `~/.claude/projects/`, `~/.codex/sessions/`, etc. |
| Frontend shows blank | Check server is running and `NEXT_PUBLIC_API_URL` is set |
| Tests fail with DB error | Ensure `QUICKCALL_OPENTRACE_DSN` points to a running Postgres |
