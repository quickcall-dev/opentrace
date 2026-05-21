# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for daemon startup reconciliation logic."""


import json
import http.server
import threading
from pathlib import Path

import pytest

from opentrace.daemon.config import DaemonConfig
from opentrace.daemon.main import Daemon
from opentrace.daemon.state import FileState, StateManager


@pytest.fixture
def tmp_config(tmp_path: Path) -> DaemonConfig:
    return DaemonConfig(base_dir=tmp_path)


@pytest.fixture
def state_mgr(tmp_config: DaemonConfig) -> StateManager:
    mgr = StateManager(state_file=tmp_config.state_file)
    mgr.load()
    return mgr


def _make_sync_server(response_data: list[dict]) -> http.server.HTTPServer:
    """Start a tiny HTTP server on a random available port that serves /api/sync."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/sync":
                body = json.dumps(response_data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass  # suppress logs

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    return server


@pytest.fixture
def sync_server():
    """Fixture that yields a factory for creating sync servers with dynamic ports."""
    servers = []

    def _create(response_data: list[dict]) -> tuple[http.server.HTTPServer, int]:
        server = _make_sync_server(response_data)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        servers.append((server, thread))
        return server, port

    yield _create

    for server, thread in servers:
        server.shutdown()
        thread.join(timeout=5)


class TestReconcileServerUnreachable:
    def test_skips_gracefully_when_server_down(self, tmp_config, state_mgr):
        """If server is unreachable, reconciliation is skipped and state unchanged."""
        state_mgr.set_state(
            FileState(file_path="/tmp/a.jsonl", source="claude_code", last_line_processed=100)
        )
        state_mgr.save()

        # Point at a port nothing is listening on
        daemon = Daemon(config=DaemonConfig(
            base_dir=tmp_config.base_dir,
            ingest_url="http://127.0.0.1:19999/ingest",
        ))
        daemon.state_mgr.load()
        daemon._reconcile()

        # State should be untouched
        assert daemon.state_mgr.get_state("/tmp/a.jsonl").last_line_processed == 100


class TestReconcileJSONLSources:
    def test_keeps_state_when_server_has_nothing(self, tmp_config, sync_server):
        """JSONL file tracked locally but server has no data → keep local state.

        The server may already have the messages via ON CONFLICT dedup. Resetting
        would cause wasteful re-pushing. Conservative approach: keep local state.
        """
        server, port = sync_server([])
        config = DaemonConfig(
            base_dir=tmp_config.base_dir,
            ingest_url=f"http://127.0.0.1:{port}/ingest",
        )
        daemon = Daemon(config=config)
        daemon.state_mgr.load()
        daemon.state_mgr.set_state(
            FileState(file_path="/tmp/a.jsonl", source="claude_code", last_line_processed=50)
        )

        daemon._reconcile()
        state = daemon.state_mgr.get_state("/tmp/a.jsonl")
        assert state is not None
        assert state.last_line_processed == 50

    def test_rewinds_when_server_behind(self, tmp_config, sync_server):
        """JSONL file where server has fewer lines → rewind to server position."""
        server, port = sync_server([
            {"raw_file_path": "/tmp/a.jsonl", "source": "claude_code",
             "message_count": 30, "max_line": 60, "last_line_read": 60},
        ])
        config = DaemonConfig(
            base_dir=tmp_config.base_dir,
            ingest_url=f"http://127.0.0.1:{port}/ingest",
        )
        daemon = Daemon(config=config)
        daemon.state_mgr.load()
        daemon.state_mgr.set_state(
            FileState(file_path="/tmp/a.jsonl", source="claude_code", last_line_processed=100)
        )

        daemon._reconcile()
        state = daemon.state_mgr.get_state("/tmp/a.jsonl")
        assert state is not None
        assert state.last_line_processed == 60

    def test_prefers_last_line_read_over_max_line(self, tmp_config, sync_server):
        """last_line_read should be used for reconciliation instead of max_line."""
        server, port = sync_server([
            {"raw_file_path": "/tmp/a.jsonl", "source": "claude_code",
             "message_count": 30, "max_line": 50, "last_line_read": 80},
        ])
        config = DaemonConfig(
            base_dir=tmp_config.base_dir,
            ingest_url=f"http://127.0.0.1:{port}/ingest",
        )
        daemon = Daemon(config=config)
        daemon.state_mgr.load()
        daemon.state_mgr.set_state(
            FileState(file_path="/tmp/a.jsonl", source="claude_code", last_line_processed=100)
        )

        daemon._reconcile()
        state = daemon.state_mgr.get_state("/tmp/a.jsonl")
        assert state is not None
        # Should use last_line_read (80), not max_line (50)
        assert state.last_line_processed == 80

    def test_falls_back_to_max_line_when_no_progress(self, tmp_config, sync_server):
        """When last_line_read is 0 (no file_progress entry), fall back to max_line."""
        server, port = sync_server([
            {"raw_file_path": "/tmp/a.jsonl", "source": "claude_code",
             "message_count": 30, "max_line": 50, "last_line_read": 0},
        ])
        config = DaemonConfig(
            base_dir=tmp_config.base_dir,
            ingest_url=f"http://127.0.0.1:{port}/ingest",
        )
        daemon = Daemon(config=config)
        daemon.state_mgr.load()
        daemon.state_mgr.set_state(
            FileState(file_path="/tmp/a.jsonl", source="claude_code", last_line_processed=100)
        )

        daemon._reconcile()
        state = daemon.state_mgr.get_state("/tmp/a.jsonl")
        assert state is not None
        assert state.last_line_processed == 50

    def test_no_reset_when_server_matches(self, tmp_config, sync_server):
        """If server is at the same line, no reset needed."""
        server, port = sync_server([
            {"raw_file_path": "/tmp/a.jsonl", "source": "codex_cli",
             "message_count": 100, "max_line": 100, "last_line_read": 100},
        ])
        config = DaemonConfig(
            base_dir=tmp_config.base_dir,
            ingest_url=f"http://127.0.0.1:{port}/ingest",
        )
        daemon = Daemon(config=config)
        daemon.state_mgr.load()
        daemon.state_mgr.set_state(
            FileState(file_path="/tmp/a.jsonl", source="codex_cli", last_line_processed=100)
        )

        daemon._reconcile()
        state = daemon.state_mgr.get_state("/tmp/a.jsonl")
        assert state is not None
        assert state.last_line_processed == 100


class TestReconcileHashSources:
    def test_keeps_state_when_server_has_nothing(self, tmp_config, sync_server):
        """Hash-based file tracked locally but server has no data → keep local state."""
        server, port = sync_server([])
        config = DaemonConfig(
            base_dir=tmp_config.base_dir,
            ingest_url=f"http://127.0.0.1:{port}/ingest",
        )
        daemon = Daemon(config=config)
        daemon.state_mgr.load()
        daemon.state_mgr.set_state(
            FileState(file_path="/tmp/session.json", source="gemini_cli", content_hash="abc123")
        )

        daemon._reconcile()
        state = daemon.state_mgr.get_state("/tmp/session.json")
        assert state is not None
        assert state.content_hash == "abc123"

    def test_resets_when_server_has_zero_messages(self, tmp_config, sync_server):
        """Hash-based file where server has 0 messages → reset."""
        server, port = sync_server([
            {"raw_file_path": "/tmp/transcript.txt", "source": "cursor",
             "message_count": 0, "max_line": 0},
        ])
        config = DaemonConfig(
            base_dir=tmp_config.base_dir,
            ingest_url=f"http://127.0.0.1:{port}/ingest",
        )
        daemon = Daemon(config=config)
        daemon.state_mgr.load()
        daemon.state_mgr.set_state(
            FileState(file_path="/tmp/transcript.txt", source="cursor", content_hash="def456")
        )

        daemon._reconcile()
        assert daemon.state_mgr.get_state("/tmp/transcript.txt") is None

    def test_no_reset_when_server_has_data(self, tmp_config, sync_server):
        """Hash-based file where server has messages → no reset."""
        server, port = sync_server([
            {"raw_file_path": "/tmp/session.json", "source": "gemini_cli",
             "message_count": 15, "max_line": 0},
        ])
        config = DaemonConfig(
            base_dir=tmp_config.base_dir,
            ingest_url=f"http://127.0.0.1:{port}/ingest",
        )
        daemon = Daemon(config=config)
        daemon.state_mgr.load()
        daemon.state_mgr.set_state(
            FileState(file_path="/tmp/session.json", source="gemini_cli", content_hash="abc123")
        )

        daemon._reconcile()
        state = daemon.state_mgr.get_state("/tmp/session.json")
        assert state is not None
        assert state.content_hash == "abc123"


class TestReconcileMixed:
    def test_multiple_files_mixed_sources(self, tmp_config, sync_server):
        """Mix of JSONL and hash sources, some need reset, some don't."""
        server, port = sync_server([
            {"raw_file_path": "/tmp/a.jsonl", "source": "claude_code",
             "message_count": 30, "max_line": 50, "last_line_read": 50},
            {"raw_file_path": "/tmp/b.json", "source": "gemini_cli",
             "message_count": 10, "max_line": 0, "last_line_read": 0},
        ])
        config = DaemonConfig(
            base_dir=tmp_config.base_dir,
            ingest_url=f"http://127.0.0.1:{port}/ingest",
        )
        daemon = Daemon(config=config)
        daemon.state_mgr.load()

        # File A: claude_code, server is behind
        daemon.state_mgr.set_state(
            FileState(file_path="/tmp/a.jsonl", source="claude_code", last_line_processed=100)
        )
        # File B: gemini_cli, server has data — should NOT reset
        daemon.state_mgr.set_state(
            FileState(file_path="/tmp/b.json", source="gemini_cli", content_hash="xyz")
        )
        # File C: codex_cli, server has nothing — should keep local state
        daemon.state_mgr.set_state(
            FileState(file_path="/tmp/c.jsonl", source="codex_cli", last_line_processed=200)
        )

        daemon._reconcile()

        # A: rewound to 50
        a = daemon.state_mgr.get_state("/tmp/a.jsonl")
        assert a is not None
        assert a.last_line_processed == 50

        # B: untouched
        b = daemon.state_mgr.get_state("/tmp/b.json")
        assert b is not None
        assert b.content_hash == "xyz"

        # C: kept as-is (server had nothing — conservative, don't reset)
        c = daemon.state_mgr.get_state("/tmp/c.jsonl")
        assert c is not None
        assert c.last_line_processed == 200
