# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for git metadata backfill (issue #74).

Tests cover:
1. extract_session_meta() for each source type
2. _backfill_session_metadata() with a real HTTP server
"""


import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import pytest

from opentrace.daemon.collector import extract_session_meta
from opentrace.daemon.config import DaemonConfig
from opentrace.daemon.main import Daemon
from opentrace.daemon.state import FileState
from opentrace.utils.repo_resolver import RepoInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dummy_server():
    """Start a real HTTP server that captures POSTed messages."""
    received: list[list[dict]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            if self.path == "/ingest":
                received.append(json.loads(body))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'[]')

        def log_message(self, format, *args):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield port, received
    srv.shutdown()


@pytest.fixture
def tmp_config(tmp_path: Path, dummy_server) -> DaemonConfig:
    port, _ = dummy_server
    return DaemonConfig(
        base_dir=tmp_path,
        ingest_url=f"http://127.0.0.1:{port}/ingest",
        poll_interval=0.01,
        batch_size=50,
        org="test-org",
    )


@pytest.fixture
def daemon(tmp_config: DaemonConfig) -> Daemon:
    d = Daemon(config=tmp_config)
    d.state_mgr.load()
    d.device_name = "test-host"
    d.global_email = "test@example.com"
    d.global_name = "Test User"
    return d


# ---------------------------------------------------------------------------
# extract_session_meta tests
# ---------------------------------------------------------------------------

class TestExtractSessionMeta:

    def test_claude_code(self, tmp_path: Path):
        """Extracts sessionId and cwd from Claude Code JSONL."""
        f = tmp_path / "session.jsonl"
        f.write_text(
            json.dumps({"sessionId": "sess-abc", "cwd": "/home/user/project", "type": "user"}) + "\n"
            + json.dumps({"type": "assistant", "content": "hi"}) + "\n"
        )
        session_id, cwd = extract_session_meta(str(f), "claude_code")
        assert session_id == "sess-abc"
        assert cwd == "/home/user/project"

    def test_codex_cli(self, tmp_path: Path):
        """Extracts session_id and cwd from Codex CLI JSONL."""
        f = tmp_path / "session.jsonl"
        f.write_text(
            json.dumps({"id": "codex-123", "cwd": "/home/user/repo"}) + "\n"
        )
        session_id, cwd = extract_session_meta(str(f), "codex_cli")
        assert session_id == "codex-123"
        assert cwd == "/home/user/repo"

    def test_cursor(self, tmp_path: Path):
        """Extracts session_id from filename UUID and cwd from slug."""
        file_path = "/home/user/.cursor/projects/Users-user-myproject/agent-transcripts/a1b2c3d4-e5f6-7890-abcd-ef1234567890.md"
        with patch("opentrace.daemon.collector.decode_cursor_slug", return_value="/Users/user/myproject"):
            session_id, cwd = extract_session_meta(file_path, "cursor")
        assert session_id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert cwd == "/Users/user/myproject"

    def test_gemini_returns_none(self):
        """Gemini sessions are skipped (no branch capture)."""
        session_id, cwd = extract_session_meta("/fake/path", "gemini_cli")
        assert session_id is None
        assert cwd is None

    def test_missing_file(self):
        """Non-existent file returns (None, None) without raising."""
        session_id, cwd = extract_session_meta("/nonexistent/file.jsonl", "claude_code")
        assert session_id is None
        assert cwd is None

    def test_malformed_json(self, tmp_path: Path):
        """Malformed JSON lines are skipped gracefully."""
        f = tmp_path / "bad.jsonl"
        f.write_text("not json\n" + json.dumps({"sessionId": "s1", "cwd": "/a"}) + "\n")
        session_id, cwd = extract_session_meta(str(f), "claude_code")
        assert session_id == "s1"
        assert cwd == "/a"


# ---------------------------------------------------------------------------
# _read_first_timestamp tests
# ---------------------------------------------------------------------------

class TestReadFirstTimestamp:

    def test_reads_first_timestamp_from_jsonl(self, tmp_path: Path):
        """Returns the first valid timestamp from a JSONL file."""
        f = tmp_path / "session.jsonl"
        f.write_text(
            json.dumps({"timestamp": "2025-10-15T06:59:51.123Z", "type": "session_meta"}) + "\n"
            + json.dumps({"timestamp": "2025-10-15T07:00:00.000Z", "type": "user"}) + "\n"
        )
        ts = Daemon._read_first_timestamp(str(f))
        assert ts == "2025-10-15T06:59:51.123Z"

    def test_skips_blank_lines(self, tmp_path: Path):
        """Skips blank lines and returns the first valid timestamp."""
        f = tmp_path / "session.jsonl"
        f.write_text(
            "\n\n"
            + json.dumps({"timestamp": "2026-02-11T12:07:20.398Z"}) + "\n"
        )
        ts = Daemon._read_first_timestamp(str(f))
        assert ts == "2026-02-11T12:07:20.398Z"

    def test_skips_malformed_json(self, tmp_path: Path):
        """Skips malformed JSON and reads from the next valid line."""
        f = tmp_path / "session.jsonl"
        f.write_text(
            "not valid json\n"
            + json.dumps({"timestamp": "2025-10-01T10:00:00Z"}) + "\n"
        )
        ts = Daemon._read_first_timestamp(str(f))
        assert ts == "2025-10-01T10:00:00Z"

    def test_skips_missing_timestamp_field(self, tmp_path: Path):
        """Skips lines without a timestamp field."""
        f = tmp_path / "session.jsonl"
        f.write_text(
            json.dumps({"type": "meta"}) + "\n"
            + json.dumps({"timestamp": "2025-09-12T10:47:38.116Z"}) + "\n"
        )
        ts = Daemon._read_first_timestamp(str(f))
        assert ts == "2025-09-12T10:47:38.116Z"

    def test_fallback_on_missing_file(self):
        """Returns current UTC time if the file doesn't exist."""
        ts = Daemon._read_first_timestamp("/nonexistent/path.jsonl")
        # Should be a valid ISO timestamp, not epoch
        assert ts > "2025"

    def test_fallback_on_empty_file(self, tmp_path: Path):
        """Returns current UTC time if the file is empty."""
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        ts = Daemon._read_first_timestamp(str(f))
        assert ts > "2025"

    def test_codex_timestamp_format(self, tmp_path: Path):
        """Handles Codex CLI timestamp format (same ISO 8601)."""
        f = tmp_path / "rollout.jsonl"
        f.write_text(
            json.dumps({"timestamp": "2026-02-04T11:14:26.090Z", "type": "session_meta"}) + "\n"
        )
        ts = Daemon._read_first_timestamp(str(f))
        assert ts == "2026-02-04T11:14:26.090Z"


# ---------------------------------------------------------------------------
# _backfill_session_metadata integration test
# ---------------------------------------------------------------------------

class TestBackfillSessionMetadata:

    def test_backfill_pushes_metadata(self, daemon: Daemon, dummy_server, tmp_path: Path):
        """Backfill resolves git info and pushes a message to the server."""
        port, received = dummy_server

        session_file = tmp_path / "session.jsonl"
        session_file.write_text(
            json.dumps({"sessionId": "sess-backfill-1", "cwd": "/Users/test/repo"}) + "\n"
        )

        state = FileState(
            file_path=str(session_file),
            source="claude_code",
            last_line_processed=1,
        )
        daemon.state_mgr.set_state(state)

        mock_repo = RepoInfo(
            cwd="/Users/test/repo",
            git_branch="main",
            repo_name="test/repo",
            repo_url="https://github.com/test/repo.git",
            git_commit="abc123",
        )
        with patch("opentrace.daemon.main.resolve_repo", return_value=mock_repo):
            daemon._backfill_session_metadata()

        assert len(received) == 1
        batch = received[0]
        assert len(batch) == 1
        msg = batch[0]
        assert msg["session_id"] == "sess-backfill-1"
        assert msg["id"] == "backfill-sess-backfill-1"
        assert msg["session_context"]["git_branch"] == "main"
        assert msg["session_context"]["repo_name"] == "test/repo"
        assert msg["session_context"]["org"] == "test-org"

    def test_backfill_uses_file_timestamp(self, daemon: Daemon, dummy_server, tmp_path: Path):
        """Backfill message timestamp should come from the session file, not epoch."""
        _, received = dummy_server

        session_file = tmp_path / "session_ts.jsonl"
        session_file.write_text(
            json.dumps({"sessionId": "sess-ts-1", "cwd": "/Users/test/repo", "timestamp": "2025-10-15T06:59:51.123Z"}) + "\n"
            + json.dumps({"type": "user", "timestamp": "2025-10-15T07:00:00.000Z"}) + "\n"
        )

        state = FileState(file_path=str(session_file), source="claude_code", last_line_processed=1)
        daemon.state_mgr.set_state(state)

        mock_repo = RepoInfo(cwd="/Users/test/repo", git_branch="main", repo_name="test/repo")
        with patch("opentrace.daemon.main.resolve_repo", return_value=mock_repo):
            daemon._backfill_session_metadata()

        assert len(received) == 1
        msg = received[0][0]
        assert msg["timestamp"] == "2025-10-15T06:59:51.123Z"

    def test_backfill_skips_when_no_cwd(self, daemon: Daemon, dummy_server, tmp_path: Path):
        """Backfill skips files where cwd can't be extracted."""
        _, received = dummy_server

        session_file = tmp_path / "empty.jsonl"
        session_file.write_text("")

        state = FileState(file_path=str(session_file), source="claude_code", last_line_processed=0)
        daemon.state_mgr.set_state(state)

        daemon._backfill_session_metadata()
        assert len(received) == 0

    def test_backfill_skips_when_no_git_info(self, daemon: Daemon, dummy_server, tmp_path: Path):
        """Backfill skips files where resolve_repo returns no branch/repo."""
        _, received = dummy_server

        session_file = tmp_path / "nogit.jsonl"
        session_file.write_text(
            json.dumps({"sessionId": "sess-nogit", "cwd": "/tmp/no-repo"}) + "\n"
        )

        state = FileState(file_path=str(session_file), source="claude_code", last_line_processed=1)
        daemon.state_mgr.set_state(state)

        mock_repo = RepoInfo(cwd="/tmp/no-repo")
        with patch("opentrace.daemon.main.resolve_repo", return_value=mock_repo):
            daemon._backfill_session_metadata()

        assert len(received) == 0

    def test_backfill_skips_gemini(self, daemon: Daemon, dummy_server, tmp_path: Path):
        """Backfill skips gemini_cli files entirely."""
        _, received = dummy_server

        state = FileState(file_path="/fake/gemini.json", source="gemini_cli", last_line_processed=0)
        daemon.state_mgr.set_state(state)

        daemon._backfill_session_metadata()
        assert len(received) == 0

    def test_backfill_handles_resolve_error(self, daemon: Daemon, dummy_server, tmp_path: Path):
        """Backfill gracefully handles resolve_repo exceptions."""
        _, received = dummy_server

        session_file = tmp_path / "error.jsonl"
        session_file.write_text(
            json.dumps({"sessionId": "sess-err", "cwd": "/broken/path"}) + "\n"
        )

        state = FileState(file_path=str(session_file), source="claude_code", last_line_processed=1)
        daemon.state_mgr.set_state(state)

        with patch("opentrace.daemon.main.resolve_repo", side_effect=OSError("access denied")):
            daemon._backfill_session_metadata()

        assert len(received) == 0

    def test_backfill_multiple_sessions(self, daemon: Daemon, dummy_server, tmp_path: Path):
        """Backfill processes multiple sessions, pushing one message each."""
        _, received = dummy_server

        for i in range(3):
            f = tmp_path / f"sess-{i}.jsonl"
            f.write_text(json.dumps({"sessionId": f"sess-{i}", "cwd": f"/repo/{i}"}) + "\n")
            state = FileState(file_path=str(f), source="claude_code", last_line_processed=1)
            daemon.state_mgr.set_state(state)

        mock_repo = RepoInfo(cwd="/repo/0", git_branch="dev", repo_name="org/proj")
        with patch("opentrace.daemon.main.resolve_repo", return_value=mock_repo):
            daemon._backfill_session_metadata()

        assert len(received) == 3
