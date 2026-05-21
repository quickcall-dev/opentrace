# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for daemon file watcher."""

import os
import time
from pathlib import Path

import pytest

from opentrace.daemon.config import DaemonConfig
from opentrace.daemon.state import FileState, StateManager
from opentrace.daemon.watcher import ChangedFile, FileWatcher


class TestFileWatcher:
    @pytest.fixture
    def tmp_home(self, tmp_path: Path) -> Path:
        """Create a fake home directory with source file structures."""
        # Claude Code
        cc_dir = tmp_path / ".claude" / "projects" / "test-project"
        cc_dir.mkdir(parents=True)
        (cc_dir / "session1.jsonl").write_text('{"type":"user"}\n')

        # Codex CLI
        codex_dir = tmp_path / ".codex" / "sessions" / "2026" / "02" / "06"
        codex_dir.mkdir(parents=True)
        (codex_dir / "rollout-test.jsonl").write_text('{"type":"event_msg"}\n')

        # Gemini CLI
        gemini_dir = tmp_path / ".gemini" / "tmp" / "sess1" / "chats"
        gemini_dir.mkdir(parents=True)
        (gemini_dir / "session-001.json").write_text('{"sessionId":"s1"}\n')

        # Cursor
        cursor_dir = tmp_path / ".cursor" / "projects" / "proj1" / "agent-transcripts"
        cursor_dir.mkdir(parents=True)
        (cursor_dir / "composer1.txt").write_text("user:\n<user_query>\nhello\n</user_query>\n")

        return tmp_path

    @pytest.fixture
    def config(self) -> DaemonConfig:
        return DaemonConfig()

    @pytest.fixture
    def state_mgr(self, tmp_path: Path) -> StateManager:
        mgr = StateManager(state_file=tmp_path / "state.json")
        mgr.load()
        return mgr

    @pytest.fixture
    def watcher(self, config: DaemonConfig, state_mgr: StateManager, tmp_home: Path) -> FileWatcher:
        w = FileWatcher(config, state_mgr)
        w._home = str(tmp_home)
        return w

    def test_discovers_all_sources(self, watcher: FileWatcher):
        changed = watcher.get_changed_files()
        sources = {c.source for c in changed}
        assert "claude_code" in sources
        assert "codex_cli" in sources
        assert "gemini_cli" in sources
        assert "cursor" in sources

    def test_skips_unchanged_files(self, watcher: FileWatcher, state_mgr: StateManager, tmp_home: Path):
        # First scan
        changed = watcher.get_changed_files()
        assert len(changed) == 4

        # Record state for all files
        for c in changed:
            state_mgr.set_state(
                FileState(
                    file_path=c.path,
                    source=c.source,
                    last_mtime=c.mtime,
                    last_size=c.size,
                )
            )

        # Second scan — nothing changed
        changed2 = watcher.get_changed_files()
        assert len(changed2) == 0

    def test_detects_modified_file(self, watcher: FileWatcher, state_mgr: StateManager, tmp_home: Path):
        changed = watcher.get_changed_files()
        for c in changed:
            state_mgr.set_state(
                FileState(
                    file_path=c.path,
                    source=c.source,
                    last_mtime=c.mtime,
                    last_size=c.size,
                )
            )

        # Modify one file
        cc_file = tmp_home / ".claude" / "projects" / "test-project" / "session1.jsonl"
        time.sleep(0.01)  # ensure mtime changes
        cc_file.write_text('{"type":"user"}\n{"type":"assistant"}\n')

        changed2 = watcher.get_changed_files()
        assert len(changed2) == 1
        assert changed2[0].source == "claude_code"

    def test_skips_empty_files(self, watcher: FileWatcher, tmp_home: Path):
        # Create an empty file
        empty = tmp_home / ".claude" / "projects" / "test-project" / "empty.jsonl"
        empty.write_text("")

        changed = watcher.get_changed_files()
        paths = [c.path for c in changed]
        assert str(empty) not in paths

    def test_skips_oversized_files(self, watcher: FileWatcher, tmp_home: Path):
        watcher._config.max_file_size = 10  # 10 bytes
        changed = watcher.get_changed_files()
        # All files are > 10 bytes except maybe empty, so most should be skipped
        for c in changed:
            assert os.path.getsize(c.path) <= 10

    def test_skips_max_retries(self, watcher: FileWatcher, state_mgr: StateManager, tmp_home: Path):
        changed = watcher.get_changed_files()
        assert len(changed) > 0

        # Mark first file as having max retries at current mtime
        first = changed[0]
        state_mgr.set_state(
            FileState(
                file_path=first.path,
                source=first.source,
                retry_count=3,
                last_mtime=first.mtime,
                last_size=first.size,
            )
        )

        changed2 = watcher.get_changed_files()
        paths2 = [c.path for c in changed2]
        assert first.path not in paths2

    def test_changed_file_dataclass(self):
        cf = ChangedFile(path="/tmp/x.jsonl", source="claude_code", mtime=1.0, size=100)
        assert cf.path == "/tmp/x.jsonl"
        assert cf.source == "claude_code"

    def test_vscdb_wal_change_triggers_rescan(self, tmp_home: Path, config: DaemonConfig, state_mgr: StateManager):
        """WAL file changes should trigger re-scan even if main .vscdb is unchanged.

        SQLite WAL mode writes to state.vscdb-wal, not the main DB.
        The watcher must check both files to detect new Cursor sessions.
        """
        # Create a fake vscdb
        vscdb_dir = tmp_home / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage"
        vscdb_dir.mkdir(parents=True)
        vscdb = vscdb_dir / "state.vscdb"
        vscdb.write_bytes(b"\x00" * 100)

        config.cursor_vscdb_glob = "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
        watcher = FileWatcher(config, state_mgr)
        watcher._home = str(tmp_home)

        # First scan picks it up
        changed = [c for c in watcher.get_changed_files() if c.source == "cursor_vscdb"]
        assert len(changed) == 1

        # Record state
        state_mgr.set_state(FileState(
            file_path=changed[0].path, source="cursor_vscdb",
            last_mtime=changed[0].mtime, last_size=changed[0].size,
        ))

        # Second scan — no change, skipped
        changed2 = [c for c in watcher.get_changed_files() if c.source == "cursor_vscdb"]
        assert len(changed2) == 0

        # Now create a WAL file (simulating Cursor writing new data)
        time.sleep(0.01)
        wal = vscdb_dir / "state.vscdb-wal"
        wal.write_bytes(b"\x00" * 50)

        # Third scan — WAL changed, should trigger re-scan
        changed3 = [c for c in watcher.get_changed_files() if c.source == "cursor_vscdb"]
        assert len(changed3) == 1, "WAL change should trigger re-scan of vscdb"
