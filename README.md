# QuickCall OpenTrace

Multi-CLI AI coding session tracer. Normalize, store, and browse sessions from Claude Code, Codex CLI, Gemini CLI, Cursor, and pi.dev — in one PostgreSQL database with a web UI.

<table>
  <tr>
    <td width="50%">
      <a href=".github/images/demo.png">
        <img src=".github/images/demo.png" alt="Session Browser" width="100%"/>
      </a>
      <p align="center"><sub>Session Browser — Search, filter, and inspect messages</sub></p>
    </td>
    <td width="50%">
      <a href=".github/images/parallel-sessions.png">
        <img src=".github/images/parallel-sessions.png" alt="Parallel Session View" width="100%"/>
      </a>
      <p align="center"><sub>Parallel Session View — Side-by-side comparison</sub></p>
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

### Full stack (with web UI)

```bash
git clone https://github.com/quickcall-dev/opentrace.git
cd opentrace
docker compose up -d
open http://localhost:3000
```

### Backend only (PyPI)

```bash
pip install quickcall-opentrace
export QUICKCALL_OPENTRACE_DSN="postgresql://user:pass@localhost:5432/quickcall"
quickcall init
quickcall-server     # :19777
quickcall-daemon     # file watcher
```

The frontend is Docker-only. The PyPI package provides server + daemon CLIs only.

Run `quickcall doctor` to verify your setup.

See [Bring Your Own Postgres](docs/guide/bring-your-own-postgres.md) for BYOP setup, multiple machines, and background mode.

## Architecture

Full architecture and schema decisions: [docs/architecture/README.md](docs/architecture/README.md)

```mermaid
flowchart LR
    subgraph Host
        A[Claude Code] --> D
        B[Codex CLI] --> D
        C1[Cursor] --> D
        C2[pi.dev] --> D
        C3[Gemini CLI] --> D
    end

    D["Daemon\n(file watcher + normalizer)"] --> |"HTTP batches"| S["Ingest Server\n:19777"]
    S --> |"COPY writes"| P[(PostgreSQL)]
    P --> |"API queries"| F["Frontend\nNext.js 15 :3000"]
```

1. **Daemon** watches `~/.claude`, `~/.codex`, `~/.gemini`, `~/.cursor`, `~/.pi`
2. **Collector** normalizes each CLI format to `NormalizedMessage`
3. **Pusher** batches messages to the ingest server
4. **Server** validates, deduplicates, writes via `COPY`
5. **Frontend** renders sessions with gantt, messages, minimap

## Installation

| Method | Command | Includes UI |
|--------|---------|-------------|
| Docker (recommended) | `git clone ... && docker compose up -d` | Yes |
| Source | `uv sync --extra dev` | Yes (run frontend separately) |
| PyPI | `pip install quickcall-opentrace` | No |

## Configuration

All variables use the `QUICKCALL_OPENTRACE_` prefix.

| Variable | Used by | Default | Description |
|----------|---------|---------|-------------|
| `DSN` | server | `postgresql://quickcall:quickcall@db:5432/quickcall` | Postgres connection string |
| `HOST` | server | `0.0.0.0` | Bind interface |
| `ADMIN_KEYS` | server | `admin_dev` | Comma-separated admin API keys |
| `PUSH_KEYS` | server | `push_dev` | Comma-separated ingest API keys |
| `INGEST_URL` | daemon | `http://localhost:19777/ingest` | Push endpoint |
| `API_KEY` | daemon | — | API key for pushes |

See `.env.example` for a complete reference.

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | — | Health check |
| POST | `/ingest` | Push | Submit normalized messages |
| GET | `/api/sessions` | Admin | List sessions |
| GET | `/api/messages` | Admin | Messages for a session |
| GET | `/api/stats` | Admin | Aggregate stats |
| GET | `/api/sync` | Admin | File sync state |

## Development

```bash
# Setup
uv sync --extra dev

# Start dependencies
docker compose up -d db

# Terminal 1 — Server
uv run python -m opentrace.server

# Terminal 2 — Daemon
uv run python -m opentrace.daemon

# Terminal 3 — Frontend
cd frontend && npm install && npm run dev

# Tests
uv run pytest

# Lint
uv run ruff check opentrace/ tests/
uv run ruff format opentrace/ tests/

# Rebuild Docker
docker compose up -d --build server daemon
docker compose up -d --build frontend

# Pre-push validation
./scripts/e2e-pypi-smoke-test.sh
./scripts/e2e-docker-smoke-test.sh
```

### Git hooks

```bash
git config core.hooksPath .githooks
```

Commits must follow conventional format (`fix:`, `feat:`, etc.) and include a `Why:` section with 2+ bullets.

### Wipe and re-ingest

```bash
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

## Documentation

| Doc | What's inside |
|-----|---------------|
| [Architecture](docs/architecture/README.md) | Schema decisions, data flow, component design |
| [BYOP Guide](docs/guide/bring-your-own-postgres.md) | Own Postgres, multiple machines, background mode |
| [Dev Environment](docs/guide/dev-environment.md) | Full local setup, IDE config, troubleshooting |
| [Publishing](docs/guide/pypi-publish.md) | PyPI release checklist and version bumping |
| [Guide Index](docs/guide/README.md) | All user and contributor guides |

## License

Apache 2.0 — see [LICENSE](LICENSE).
