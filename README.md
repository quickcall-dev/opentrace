# QuickCall OpenTrace

Multi-CLI AI coding session tracer. Normalize, store, and browse sessions from Claude Code, Codex CLI, Gemini CLI, Cursor, and pi.dev — in one PostgreSQL database with a web UI.

<table>
  <tr>
    <td width="50%">
      <a href=".github/images/demo.png">
        <img src=".github/images/demo.png" alt="Session Browser — Search, filter, and inspect messages with rich rendering" width="100%"/>
      </a>
      <p align="center"><sub>Session Browser — Search, filter, and inspect messages</sub></p>
    </td>
    <td width="50%">
      <a href=".github/images/parallel-sessions.png">
        <img src=".github/images/parallel-sessions.png" alt="Parallel Session View — Side-by-side comparison of related sessions" width="100%"/>
      </a>
      <p align="center"><sub>Parallel Session View — Side-by-side comparison of related sessions</sub></p>
    </td>
  </tr>
</table>

## Supported CLIs

| CLI | Data source | Notes |
|-----|-------------|-------|
| **Claude Code** | `~/.claude/projects/**/*.jsonl` | Full message + tool history |
| **Codex CLI** | `~/.codex/sessions/*/*/*/rollout-*.jsonl` | Token usage, tool calls |
| **Gemini CLI** | `~/.gemini/tmp/*/chats/session-*.json` | Shell commands, file edits |
| **Cursor** | `~/.cursor/projects/*/agent-transcripts/*.txt` + state.vscdb | Agent transcripts, composer data |
| **pi.dev** | `~/.pi/agent/sessions/**/*.jsonl` | Kimi model, thinking blocks |

## Quick Start

### Full experience (with web UI)

```bash
git clone https://github.com/quickcall-dev/opentrace.git
cd opentrace
docker compose up -d
open http://localhost:3000   # macOS
# xdg-open http://localhost:3000  # Linux
```

`quickcall up` is a convenience wrapper for `docker compose up -d`. Both require Docker.

### Backend only (no UI)

```bash
pip install quickcall-opentrace
export QUICKCALL_OPENTRACE_DSN="postgresql://user:pass@localhost:5432/quickcall"
quickcall init       # creates ~/.quickcall-opentrace/config.json
quickcall-server     # ingest API on :19777
quickcall-daemon     # file watcher + normalizer
```

The daemon watches local session directories and pushes normalized batches to the ingest server automatically.

**Note:** `pip install` gives you the Python backend only (server + daemon CLIs). The web frontend is available only via Docker Compose.

See [Bring Your Own Postgres guide](docs/guide/bring-your-own-postgres.md) for full details — bring your own Postgres, multiple machines, background mode, troubleshooting.

Not sure what's wrong? Run `quickcall doctor` — it checks Docker, Postgres, server, daemon, and session dirs, then prints next steps.

## Architecture

Full architecture document: [docs/architecture/README.md](docs/architecture/README.md)

```mermaid
flowchart LR
    subgraph Host["Host Machine"]
        A[Claude Code] --> D
        B[Codex CLI] --> D
        C1[Cursor] --> D
        C2[pi.dev] --> D
        C3[Gemini CLI] --> D
    end

    D["Daemon<br/>(file watcher + normalizer)"] -->|"HTTP batches"| S["Ingest Server<br/>(port 19777)"]
    S -->|"COPY writes"| P[("PostgreSQL")]
    P -->|"API queries"| F["Frontend<br/>(Next.js 15, port 3000)"]

    style Host fill:#f5f5f5,stroke:#999
    style D fill:#e3f2fd,stroke:#1976d2
    style S fill:#fff3e0,stroke:#f57c00
    style P fill:#e8f5e9,stroke:#388e3c
    style F fill:#f3e5f5,stroke:#7b1fa2
```

1. **Daemon** polls `~/.claude`, `~/.codex`, `~/.gemini`, `~/.cursor`, `~/.pi` for new session files
2. **Collector** normalizes each CLI's format into `NormalizedMessage`
3. **Pusher** batches messages to the ingest server over HTTP
4. **Server** validates, deduplicates, and writes to PostgreSQL via `COPY`
5. **Frontend** queries the API and renders sessions with sidebar gantt, messages, minimap

## Installation

### Docker (recommended)

```bash
git clone https://github.com/quickcall-dev/opentrace.git
cd opentrace
quickcall up
# Or directly: docker compose up -d
```

### From source

```bash
uv sync --extra dev
uv run pytest
```

### PyPI (backend only)

```bash
pip install quickcall-opentrace
```

This installs the `quickcall-server` and `quickcall-daemon` CLIs. For the full stack with the web UI, clone the repo and use `quickcall up`.

For running with your own PostgreSQL database (no Docker), see the [Bring Your Own Postgres guide](docs/guide/bring-your-own-postgres.md).

## Configuration

All runtime environment variables use the `QUICKCALL_OPENTRACE_` prefix.

| Variable | Used by | Default | Description |
|----------|---------|---------|-------------|
| `QUICKCALL_OPENTRACE_DSN` | server | `postgresql://quickcall:quickcall@db:5432/quickcall` | PostgreSQL connection string |
| `QUICKCALL_OPENTRACE_HOST` | server | `0.0.0.0` | Server bind interface |
| `QUICKCALL_OPENTRACE_ADMIN_KEYS` | server | `admin_dev` | Comma-separated admin API keys |
| `QUICKCALL_OPENTRACE_PUSH_KEYS` | server | `push_dev` | Comma-separated ingest API keys |
| `QUICKCALL_OPENTRACE_INGEST_URL` | daemon | `http://localhost:19777/ingest` | Daemon push endpoint |
| `QUICKCALL_OPENTRACE_API_KEY` | daemon | — | API key for daemon pushes |

See `.env.example` for a complete reference.

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | — | Health check |
| POST | `/ingest` | Push | Submit normalized messages |
| GET | `/api/sessions` | Admin | List sessions with filters |
| GET | `/api/messages` | Admin | Messages for a session |
| GET | `/api/stats` | Admin | Aggregate stats |
| GET | `/api/sync` | Admin | File sync state |

## Development

### Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Docker](https://docs.docker.com/get-docker/) — for Postgres and optional full-stack
- Node.js 20+ — for frontend development

### 1. Clone and install

```bash
git clone https://github.com/quickcall-dev/opentrace.git
cd opentrace
uv sync --extra dev
```

### 2. Start PostgreSQL

```bash
# Using Docker (recommended)
docker compose up -d db

# Or use your own Postgres — create database "quickcall" and set DSN:
# export QUICKCALL_OPENTRACE_DSN=postgresql://user:pass@localhost:5432/quickcall
```

Schema is applied automatically on server startup (`ensure_schema`).

### 3. Run backend natively

**Terminal 1 — Ingest server:**
```bash
uv run python -m opentrace.server
# Server starts on http://localhost:19777
```

**Terminal 2 — Daemon:**
```bash
uv run python -m opentrace.daemon
# Watches ~/.claude, ~/.codex, ~/.gemini, ~/.cursor, ~/.pi
```

Or use the CLI wrapper:
```bash
uv run quickcall-daemon
```

### 4. Run frontend natively

```bash
cd frontend
npm install
npm run dev
# Opens on http://localhost:3000
```

The frontend proxies API calls to `localhost:19777` in development.

### 5. Run tests

```bash
# All tests (requires local Postgres running)
uv run pytest

# Specific module
uv run pytest tests/daemon/

# With coverage
uv run pytest --cov=opentrace
```

### 6. Lint and format

```bash
uv run ruff check opentrace/ tests/
uv run ruff format opentrace/ tests/
```

### 7. Rebuild Docker after changes

```bash
# Backend changes (Python)
docker compose up -d --build server daemon

# Frontend changes (TypeScript/React)
docker compose up -d --build frontend
```

### 8. Pre-push validation

Run the e2e smoke tests before pushing to main:

```bash
# PyPI package path (BYOP)
./scripts/e2e-pypi-smoke-test.sh

# Docker Compose path (full stack)
./scripts/e2e-docker-smoke-test.sh
```

Both auto-clean on exit. They catch packaging and entry-point issues that unit tests miss.

### 9. Git hooks

The repo includes a pre-commit hook that enforces conventional commits:

```bash
git config core.hooksPath .githooks
```

Commits must include a `Why:` section with 2+ bullets.

### 10. Wipe and re-ingest

```bash
# Truncate DB and reset daemon state
PGPASSWORD=quickcall psql -h localhost -p 15433 -U quickcall -d quickcall -c \
  "TRUNCATE TABLE tool_calls, tool_results, token_usage, messages, file_progress, sessions, schema_version RESTART IDENTITY CASCADE; INSERT INTO schema_version (version) VALUES (1);"
rm ~/.quickcall-opentrace/state.json ~/.quickcall-opentrace/backfilled_sessions.json 2>/dev/null
docker compose restart daemon
```

### Adding a new CLI source

1. **Schema** — Add transform in `opentrace/schemas/<source>/transform.py`
2. **Collector** — Add `_collect_<source>` in `opentrace/daemon/collector.py`
3. **Tests** — Add fixtures in `tests/fixtures/` and tests in `tests/schemas/`, `tests/daemon/`
4. **Watcher** — Add glob pattern in `opentrace/daemon/config.py` if needed

## License

Apache 2.0 — see [LICENSE](LICENSE).
