# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for reingest state reset helpers."""

from datetime import datetime, timezone
from pathlib import Path

from opentrace.daemon.state import FileState, StateManager


# ---------------------------------------------------------------------------
# StateManager reset method tests
# ---------------------------------------------------------------------------


class TestStateManagerResets:
    """Test reset_all, reset_by_source, reset_since."""

    def _make_state(self, tmp_path: Path) -> StateManager:
        mgr = StateManager(state_file=tmp_path / "state.json")
        mgr.set_state(FileState(
            file_path="/home/user/.claude/sessions/a.jsonl",
            source="claude_code",
            last_line_processed=100,
            last_mtime=1708300000.0,
        ))
        mgr.set_state(FileState(
            file_path="/home/user/.claude/sessions/b.jsonl",
            source="claude_code",
            last_line_processed=50,
            last_mtime=1708400000.0,
        ))
        mgr.set_state(FileState(
            file_path="/home/user/.codex/history/c.jsonl",
            source="codex_cli",
            last_line_processed=30,
            last_mtime=1708200000.0,
        ))
        mgr.set_state(FileState(
            file_path="/home/user/.gemini/sessions/d.json",
            source="gemini_cli",
            content_hash="abc123",
            last_mtime=1708350000.0,
        ))
        return mgr

    def test_reset_all(self, tmp_path):
        mgr = self._make_state(tmp_path)
        assert len(mgr.all_states()) == 4
        count = mgr.reset_all()
        assert count == 4
        assert len(mgr.all_states()) == 0

    def test_reset_all_empty(self, tmp_path):
        mgr = StateManager(state_file=tmp_path / "state.json")
        count = mgr.reset_all()
        assert count == 0

    def test_reset_by_source(self, tmp_path):
        mgr = self._make_state(tmp_path)
        count = mgr.reset_by_source("claude_code")
        assert count == 2
        remaining = mgr.all_states()
        assert len(remaining) == 2
        assert all(fs.source != "claude_code" for fs in remaining.values())

    def test_reset_by_source_no_match(self, tmp_path):
        mgr = self._make_state(tmp_path)
        count = mgr.reset_by_source("cursor")
        assert count == 0
        assert len(mgr.all_states()) == 4

    def test_reset_since(self, tmp_path):
        mgr = self._make_state(tmp_path)
        # cutoff between c.jsonl (1708200000) and a.jsonl (1708300000)
        cutoff_dt = datetime.fromtimestamp(1708300000, tz=timezone.utc)
        count = mgr.reset_since(cutoff_dt.isoformat())
        # Should remove a (1708300000), b (1708400000), d (1708350000)
        assert count == 3
        remaining = mgr.all_states()
        assert len(remaining) == 1
        assert list(remaining.values())[0].source == "codex_cli"

    def test_reset_since_invalid_date(self, tmp_path):
        mgr = self._make_state(tmp_path)
        count = mgr.reset_since("not-a-date")
        assert count == 0
        assert len(mgr.all_states()) == 4

    def test_reset_state_single_file(self, tmp_path):
        mgr = self._make_state(tmp_path)
        mgr.reset_state("/home/user/.claude/sessions/a.jsonl")
        assert mgr.get_state("/home/user/.claude/sessions/a.jsonl") is None
        assert len(mgr.all_states()) == 3
