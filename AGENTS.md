# Agent Directives

> If you are an AI coding assistant (Claude, Codex, Cursor, etc.) working on this repo, read this first.

## What This Repo Is

QuickCall OpenTrace is an open-source AI coding session tracer. It reads session files from multiple CLI tools (Claude Code, Codex CLI, Gemini CLI, Cursor, pi.dev), normalizes them into a common schema, and stores them in PostgreSQL with a Next.js frontend for browsing.

## Quick Orientation

```
opentrace/
  cli/          → Entrypoints (quickcall-daemon, quickcall-server, quickcall)
  daemon/       → File watcher, collector, pusher, state manager
  db/           → Schema, migrations, reader.py, writer.py
  schemas/      → Per-CLI transforms (claude_code/, codex_cli/, cursor/, gemini_cli/, pi/)
  server/       → HTTP ingest API
  utils/        → Cursor parser, VSCDB reader, repo resolver
frontend/       → Next.js 15 app (sessions browser, gantt, minimap)
tests/          → pytest
  fixtures/     → Sample session files for testing
docs/
  guide/        → User and contributor guides
  architecture/ → Design docs and schema decisions
```

## Rules

1. **No proprietary data in commits.** No real session IDs, org slugs, personal paths, or `.env` files.
2. **Tests must pass.** `uv run pytest`
3. **Ruff clean.** `uv run ruff check opentrace/ tests/`
4. **Zero inline imports.** All imports at top of file.
5. **Conventional commits.** Prefix with `fix:`, `feat:`, `chore:`, `docs:`, `test:`
6. **All dates/times in UTC** when documenting.
7. **SPDX header on every new `.py` file:**
   ```python
   # SPDX-License-Identifier: Apache-2.0
   # Copyright 2025 Sagar Sarkale
   ```

## Adding a New CLI Source

1. Create `opentrace/schemas/<source>/transform.py` → `transform_<source>_v1()`
2. Add `opentrace/daemon/collector.py` → `_collect_<source>()`
3. Add glob pattern in `opentrace/daemon/config.py`
4. Add fixture in `tests/fixtures/` and tests in `tests/schemas/`, `tests/daemon/`
5. Add row to the Supported CLIs table in README.md

## Environment

- Python 3.11+, managed by **`uv`** (never `pip`)
- PostgreSQL 16 for data
- Node.js 20+ for frontend
- Docker Compose for full stack

## Dev Commands

```bash
uv sync --extra dev          # install deps (never pip install)
uv run pytest                # run tests
uv run ruff check .          # lint
uv run python -m opentrace.server      # start ingest server
uv run python -m opentrace.daemon      # start daemon
uv run quickcall up                    # full stack via Docker
docker compose up -d         # full stack via Docker
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
