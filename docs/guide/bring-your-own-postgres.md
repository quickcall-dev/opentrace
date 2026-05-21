# Bring Your Own Postgres

Run QuickCall OpenTrace with an existing PostgreSQL database. No Docker required.

## What you get

- **Ingest server** (`quickcall-server`) — HTTP API on port 19777
- **Daemon** (`quickcall-daemon`) — watches local CLI sessions and pushes to the server
- **PostgreSQL** — your own database, existing or new
- **No web UI** — backend only. For the full UI, use [Docker Compose](../README.md#full-experience-with-web-ui).

## Prerequisites

- Python 3.11+
- PostgreSQL 12+ (local or remote)
- One of the supported AI CLIs installed: Claude Code, Codex CLI, Gemini CLI, Cursor, or pi.dev

## Quick start

```bash
# 1. Install
pip install quickcall-opentrace

# 2. Set your Postgres connection
export QUICKCALL_OPENTRACE_DSN="postgresql://user:pass@localhost:5432/quickcall"
export QUICKCALL_OPENTRACE_ADMIN_KEYS="admin_dev"
export QUICKCALL_OPENTRACE_PUSH_KEYS="push_dev"

# 3. Initialize config (interactive)
quickcall init

# 4. Start server
quickcall-server

# 5. In another terminal, start daemon
quickcall-daemon
```

The daemon automatically discovers session directories (`~/.claude`, `~/.codex`, etc.) and begins pushing.

## Non-interactive setup (CI / automation)

```bash
printf "postgresql://user:pass@localhost:5432/quickcall\nmy_push_key\nmy_admin_key\n" | quickcall init
```

This creates `~/.quickcall-opentrace/config.json` without prompting.

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `QUICKCALL_OPENTRACE_DSN` | Yes | — | PostgreSQL connection string |
| `QUICKCALL_OPENTRACE_ADMIN_KEYS` | Yes | `admin_dev` | Comma-separated admin API keys |
| `QUICKCALL_OPENTRACE_PUSH_KEYS` | Yes | `push_dev` | Comma-separated ingest API keys |
| `QUICKCALL_OPENTRACE_API_KEY` | For daemon | — | Key the daemon sends (must match `PUSH_KEYS`) |
| `QUICKCALL_OPENTRACE_CONFIG_DIR` | No | `~/.quickcall-opentrace` | Config/state directory |

## Verify it's working

```bash
# Check health
quickcall doctor

# Daemon status
quickcall status

# Recent logs
quickcall logs -n 20
```

## Database setup

The server auto-creates tables on first start. If you prefer to create the database manually:

```bash
createdb quickcall
```

The schema is applied automatically (`ensure_schema` on server startup).

## Running in background

```bash
# Start server in background
quickcall-server &

# Start daemon in background
quickcall start

# Check later
quickcall status

# Stop daemon
quickcall stop
```

## Multiple machines, one database

Point multiple workstations at the same Postgres:

```bash
# Machine A
export QUICKCALL_OPENTRACE_DSN="postgresql://quickcall:quickcall@db.example.com:5432/opentrace"
quickcall-server

# Machine A + B + C
quickcall-daemon  # each pushes its own sessions
```

Sessions are tagged by `device_id` so you can distinguish sources.

## Pre-push validation

If you're contributing to the project, run the e2e smoke test before pushing:

```bash
./scripts/e2e-pypi-smoke-test.sh
```

This builds the wheel, installs it in a clean venv, starts Postgres, and runs the full pipeline. See [Dev Environment](dev-environment.md) for details.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `quickcall init` hangs | Your shell may not be a tty. Use the piped non-interactive mode. |
| `Could not connect to Postgres` | Check DSN host/port. Ensure Postgres accepts TCP connections. |
| `Server: unreachable` | Server not running or wrong `INGEST_URL` in config. |
| `Daemon: not running` | Run `quickcall start` or `quickcall-daemon`. |
| No sessions appearing | Check `quickcall doctor` for session dirs. Ensure you've used a supported CLI. |
