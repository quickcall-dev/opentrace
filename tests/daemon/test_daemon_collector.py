# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for daemon source collectors."""

import json
import os
from pathlib import Path
from unittest.mock import patch
import sqlite3

import pytest

from opentrace.daemon.collector import (
    collect_file,
    CollectResult,
    _build_session_context,
)
from opentrace.daemon.watcher import ChangedFile
from opentrace.utils.repo_resolver import RepoInfo

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestClaudeCollector:
    @pytest.fixture
    def claude_file(self) -> str:
        return str(FIXTURES_DIR / "claude_v1_sample.jsonl")

    @pytest.fixture
    def changed(self, claude_file: str) -> ChangedFile:
        stat = os.stat(claude_file)
        return ChangedFile(
            path=claude_file,
            source="claude_code",
            mtime=stat.st_mtime,
            size=stat.st_size,
        )

    def test_collect_all_lines(self, changed: ChangedFile):
        result = collect_file(changed, None)
        assert isinstance(result, CollectResult)
        assert len(result.messages) > 0
        assert result.new_state.source == "claude_code"
        assert result.new_state.last_line_processed > 0

    def test_collect_resumes_from_line(self, changed: ChangedFile):
        # First collect all
        result1 = collect_file(changed, None)
        last_line = result1.new_state.last_line_processed

        # Collect again from the last state — should get 0 new messages
        result2 = collect_file(changed, result1.new_state)
        assert len(result2.messages) == 0
        assert result2.new_state.last_line_processed == last_line

    def test_all_messages_are_normalized(self, changed: ChangedFile):
        result = collect_file(changed, None)
        for msg in result.messages:
            assert msg.source == "claude_code"
            assert msg.raw_file_path == changed.path


class TestCodexCollector:
    @pytest.fixture
    def codex_file(self) -> str:
        return str(FIXTURES_DIR / "codex_v1_sample.jsonl")

    @pytest.fixture
    def changed(self, codex_file: str) -> ChangedFile:
        stat = os.stat(codex_file)
        return ChangedFile(
            path=codex_file,
            source="codex_cli",
            mtime=stat.st_mtime,
            size=stat.st_size,
        )

    def test_collect_all_lines(self, changed: ChangedFile):
        result = collect_file(changed, None)
        assert isinstance(result, CollectResult)
        assert len(result.messages) > 0
        assert result.new_state.source == "codex_cli"

    def test_collect_resumes_correctly(self, changed: ChangedFile):
        result1 = collect_file(changed, None)
        # Second collect replays all lines for context but only emits new ones
        result2 = collect_file(changed, result1.new_state)
        assert len(result2.messages) == 0

    def test_repo_name_from_session_meta_git(self, tmp_path: Path):
        """Codex session_meta with git.repository_url should yield repo_name."""
        codex_with_git = tmp_path / "codex_with_git.jsonl"
        lines = [
            json.dumps({
                "timestamp": "2026-02-04T11:14:26.090Z",
                "type": "session_meta",
                "payload": {"id": "test-session", "cwd": "/tmp/fake-cwd"},
                "git": {"repository_url": "https://github.com/org/repo.git"},
            }),
            json.dumps({
                "timestamp": "2026-02-04T11:14:37.486Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "hello"},
            }),
        ]
        codex_with_git.write_text("\n".join(lines))
        changed = ChangedFile(
            path=str(codex_with_git),
            source="codex_cli",
            mtime=codex_with_git.stat().st_mtime,
            size=codex_with_git.stat().st_size,
        )
        result = collect_file(changed, None)
        assert len(result.messages) > 0
        assert result.messages[0].session_context is not None
        assert result.messages[0].session_context.repo_name == "org/repo"


class TestGeminiCollector:
    @pytest.fixture
    def gemini_file(self) -> str:
        return str(FIXTURES_DIR / "gemini_v1_sample.json")

    @pytest.fixture
    def changed(self, gemini_file: str) -> ChangedFile:
        stat = os.stat(gemini_file)
        return ChangedFile(
            path=gemini_file,
            source="gemini_cli",
            mtime=stat.st_mtime,
            size=stat.st_size,
        )

    def test_collect_full_session(self, changed: ChangedFile):
        result = collect_file(changed, None)
        assert len(result.messages) > 0
        assert result.new_state.content_hash != ""
        assert result.new_state.source == "gemini_cli"

    def test_skip_unchanged_content(self, changed: ChangedFile):
        result1 = collect_file(changed, None)
        # Second collect with same hash — should skip
        result2 = collect_file(changed, result1.new_state)
        assert len(result2.messages) == 0

    def test_reprocesses_on_hash_change(self, changed: ChangedFile):
        result1 = collect_file(changed, None)
        # Fake a different hash
        result1.new_state.content_hash = "different_hash"
        result2 = collect_file(changed, result1.new_state)
        assert len(result2.messages) > 0


class TestCursorCollector:
    @pytest.fixture
    def cursor_file(self) -> str:
        return str(FIXTURES_DIR / "cursor_transcript_sample.txt")

    @pytest.fixture
    def changed(self, cursor_file: str) -> ChangedFile:
        stat = os.stat(cursor_file)
        return ChangedFile(
            path=cursor_file,
            source="cursor",
            mtime=stat.st_mtime,
            size=stat.st_size,
        )

    def test_collect_transcript(self, changed: ChangedFile):
        result = collect_file(changed, None)
        assert len(result.messages) > 0
        assert result.new_state.content_hash != ""
        assert result.new_state.source == "cursor"

    def test_skip_unchanged_content(self, changed: ChangedFile):
        result1 = collect_file(changed, None)
        result2 = collect_file(changed, result1.new_state)
        assert len(result2.messages) == 0


class TestSessionContextPopulation:
    """Test that collectors populate SessionContext on messages."""

    @pytest.fixture
    def claude_changed(self) -> ChangedFile:
        path = str(FIXTURES_DIR / "claude_v1_sample.jsonl")
        stat = os.stat(path)
        return ChangedFile(
            path=path, source="claude_code", mtime=stat.st_mtime, size=stat.st_size
        )

    @pytest.fixture
    def gemini_changed(self) -> ChangedFile:
        path = str(FIXTURES_DIR / "gemini_v1_sample.json")
        stat = os.stat(path)
        return ChangedFile(
            path=path, source="gemini_cli", mtime=stat.st_mtime, size=stat.st_size
        )

    @patch("opentrace.daemon.collector.resolve_repo")
    def test_claude_populates_session_context(self, mock_resolve, claude_changed):
        mock_resolve.return_value = RepoInfo(
            cwd="/Users/test/project",
            repo_url="git@github.com:org/repo.git",
            repo_name="org/repo",
            git_branch="main",
            git_commit="abc123",
            user_email="local@test.com",
            user_name="Local User",
        )
        result = collect_file(
            claude_changed,
            None,
            device_name="my-host",
            global_email="global@test.com",
            global_name="Global User",
        )
        assert len(result.messages) > 0
        for msg in result.messages:
            assert msg.session_context is not None
            ctx = msg.session_context
            # Local git config should take priority over global
            assert ctx.user_email == "local@test.com"
            assert ctx.user_name == "Local User"
            assert ctx.device_name == "my-host"
            assert ctx.cwd == "/Users/test/project"
            assert ctx.repo_name == "org/repo"

    def test_gemini_populates_session_context(self, gemini_changed):
        result = collect_file(
            gemini_changed,
            None,
            device_name="my-host",
            global_email="global@test.com",
            global_name="Global User",
        )
        assert len(result.messages) > 0
        for msg in result.messages:
            assert msg.session_context is not None
            ctx = msg.session_context
            assert ctx.user_email == "global@test.com"
            assert ctx.device_name == "my-host"

    def test_build_session_context_identity_chain(self):
        """Local git email > global email > device_name."""
        with patch("opentrace.daemon.collector.resolve_repo") as mock:
            mock.return_value = RepoInfo(cwd="/some/path", user_email="local@test.com")
            ctx = _build_session_context(
                cwd="/some/path",
                global_email="global@test.com",
                global_name="Global",
                device_name="host",
            )
            assert ctx.user_email == "local@test.com"

    def test_build_session_context_falls_back_to_global(self):
        """When local git has no email, fall back to global."""
        with patch("opentrace.daemon.collector.resolve_repo") as mock:
            mock.return_value = RepoInfo(cwd="/some/path", user_email=None)
            ctx = _build_session_context(
                cwd="/some/path",
                global_email="global@test.com",
                device_name="host",
            )
            assert ctx.user_email == "global@test.com"

    def test_build_session_context_no_cwd(self):
        """When no cwd, use global identity only."""
        ctx = _build_session_context(
            global_email="global@test.com",
            global_name="Global",
            device_name="host",
        )
        assert ctx.user_email == "global@test.com"
        assert ctx.cwd is None
        assert ctx.repo_url is None

    def test_build_session_context_prefers_source_git_fields(self):
        """Pre-provided git fields (from source data) take priority over resolved."""
        with patch("opentrace.daemon.collector.resolve_repo") as mock:
            mock.return_value = RepoInfo(
                cwd="/path",
                git_branch="resolved-branch",
                git_commit="resolved-commit",
                repo_url="resolved-url",
            )
            ctx = _build_session_context(
                cwd="/path",
                git_branch="source-branch",
                git_commit="source-commit",
                repo_url="source-url",
            )
            assert ctx.git_branch == "source-branch"
            assert ctx.git_commit == "source-commit"
            assert ctx.repo_url == "source-url"

    def test_build_session_context_derives_repo_name_from_repo_url(self):
        """When resolve_repo finds no repo_name, derive it from repo_url."""
        with patch("opentrace.daemon.collector.resolve_repo") as mock:
            mock.return_value = RepoInfo(cwd="/path", repo_url=None, repo_name=None)
            ctx = _build_session_context(
                cwd="/path",
                repo_url="https://github.com/org/repo.git",
            )
            assert ctx.repo_name == "org/repo"

    def test_build_session_context_falls_back_to_repo_cache(self):
        """When resolve_repo finds no repo_name, fall back to repo cache."""
        with patch("opentrace.daemon.collector.resolve_repo") as mock:
            mock.return_value = RepoInfo(cwd="/path", repo_url=None, repo_name=None)
            with patch("opentrace.daemon.collector.load_repo_cache") as cache_mock:
                cache_mock.return_value = {"/path": "cached-org/cached-repo"}
                ctx = _build_session_context(cwd="/path")
                assert ctx.repo_name == "cached-org/cached-repo"


class TestCursorVscdbIncrementalCollector:
    """Test incremental collection for cursor_vscdb source."""

    @pytest.fixture
    def vscdb_file(self, tmp_path: Path) -> str:
        db_path = str(tmp_path / "state.vscdb")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        cd1 = {
            "createdAt": 1708000000000,
            "lastUpdatedAt": 1708000001000,
            "conversation": [
                {"type": 1, "bubbleId": "b1", "text": "Hello"},
                {"type": 2, "bubbleId": "b2", "text": "Hi"},
            ],
        }
        cd2 = {
            "createdAt": 1708000002000,
            "lastUpdatedAt": 1708000003000,
            "conversation": [
                {"type": 1, "bubbleId": "b3", "text": "Hey"},
            ],
        }
        conn.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            ("composerData:s1", json.dumps(cd1).encode()),
        )
        conn.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            ("composerData:s2", json.dumps(cd2).encode()),
        )
        conn.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            ("cursorAuth/cachedEmail", "test@example.com"),
        )
        conn.commit()
        conn.close()
        return db_path

    @pytest.fixture
    def changed(self, vscdb_file: str) -> ChangedFile:
        stat = os.stat(vscdb_file)
        return ChangedFile(
            path=vscdb_file,
            source="cursor_vscdb",
            mtime=stat.st_mtime,
            size=stat.st_size,
        )

    def test_first_collect_processes_all(self, changed: ChangedFile):
        result = collect_file(changed, None)
        assert len(result.messages) > 0
        assert result.new_state.content_hash  # JSON-encoded timestamps
        ts = json.loads(result.new_state.content_hash)
        assert "s1" in ts
        assert "s2" in ts

    def test_second_collect_skips_unchanged(self, changed: ChangedFile):
        result1 = collect_file(changed, None)
        result2 = collect_file(changed, result1.new_state)
        assert len(result2.messages) == 0

    def test_processes_only_updated_session(self, changed: ChangedFile, vscdb_file: str):
        result1 = collect_file(changed, None)
        assert len(result1.messages) > 0

        # Update only s1's lastUpdatedAt
        conn = sqlite3.connect(vscdb_file)
        cd1_updated = {
            "createdAt": 1708000000000,
            "lastUpdatedAt": 1708000099000,
            "conversation": [
                {"type": 1, "bubbleId": "b1", "text": "Hello updated"},
                {"type": 2, "bubbleId": "b2", "text": "Hi updated"},
            ],
        }
        conn.execute(
            "UPDATE ItemTable SET value = ? WHERE key = ?",
            (json.dumps(cd1_updated).encode(), "composerData:s1"),
        )
        conn.commit()
        conn.close()

        # Re-collect: only s1 should be processed
        result2 = collect_file(changed, result1.new_state)
        assert len(result2.messages) > 0
        # All messages should be from s1 session
        for msg in result2.messages:
            assert msg.session_id == "s1"


class TestPiCollector:
    @pytest.fixture
    def pi_file(self) -> str:
        return str(FIXTURES_DIR / "pi_v1_sample.jsonl")

    @pytest.fixture
    def changed(self, pi_file: str) -> ChangedFile:
        stat = os.stat(pi_file)
        return ChangedFile(
            path=pi_file,
            source="pi",
            mtime=stat.st_mtime,
            size=stat.st_size,
        )

    def test_collect_all_lines(self, changed: ChangedFile):
        result = collect_file(changed, None)
        assert isinstance(result, CollectResult)
        assert len(result.messages) > 0
        assert result.new_state.source == "pi"
        assert result.new_state.last_line_processed > 0

    def test_collect_resumes_from_line(self, changed: ChangedFile):
        # First collect all
        result1 = collect_file(changed, None)
        last_line = result1.new_state.last_line_processed

        # Collect again from the last state — should get 0 new messages
        result2 = collect_file(changed, result1.new_state)
        assert len(result2.messages) == 0
        assert result2.new_state.last_line_processed == last_line

    def test_all_messages_are_normalized(self, changed: ChangedFile):
        result = collect_file(changed, None)
        for msg in result.messages:
            assert msg.source == "pi"
            assert msg.raw_file_path == changed.path

    def test_session_id_from_session_event(self, changed: ChangedFile):
        result = collect_file(changed, None)
        assert len(result.messages) > 0
        assert result.messages[0].session_id == "test-session-pi-001"

    def test_user_and_assistant_messages(self, changed: ChangedFile):
        result = collect_file(changed, None)
        types = [m.msg_type for m in result.messages]
        assert "user" in types
        assert "assistant" in types
        assert "tool_call" in types
        assert "tool_result" in types
        assert "compaction" in types

    def test_model_passed_from_model_change(self, changed: ChangedFile):
        result = collect_file(changed, None)
        for msg in result.messages:
            if msg.msg_type == "assistant":
                assert msg.model == "test-model"
            if msg.msg_type == "tool_call":
                assert msg.model == "test-model"

    def test_skips_metadata_events(self, changed: ChangedFile):
        result = collect_file(changed, None)
        for msg in result.messages:
            assert msg.msg_type not in ("model_change", "thinking_level_change", "custom")

    def test_cwd_populates_session_context(self, changed: ChangedFile):
        result = collect_file(changed, None)
        assert len(result.messages) > 0
        assert result.messages[0].session_context is not None
        assert result.messages[0].session_context.cwd == "/home/user/project"


class TestUnknownSource:
    def test_unknown_source_raises_key_error(self):
        """collect_file raises KeyError for unknown source types (M8)."""
        changed = ChangedFile(
            path="/tmp/test.txt",
            source="unknown_source",
            mtime=1.0,
            size=100,
        )
        with pytest.raises(KeyError, match="unknown_source"):
            collect_file(changed, None)
