# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for daemon state management."""

import json
from pathlib import Path

import pytest

from opentrace.daemon.state import FileState, StateManager


class TestFileState:
    def test_to_dict_roundtrip(self):
        state = FileState(
            file_path="/tmp/test.jsonl",
            source="claude_code",
            last_line_processed=42,
            last_mtime=1000.0,
            last_size=4096,
        )
        d = state.to_dict()
        restored = FileState.from_dict(d)
        assert restored.file_path == state.file_path
        assert restored.last_line_processed == 42
        assert restored.source == "claude_code"

    def test_from_dict_ignores_extra_keys(self):
        d = {"file_path": "/tmp/x", "source": "cursor", "unknown_key": "ignored"}
        state = FileState.from_dict(d)
        assert state.file_path == "/tmp/x"
        assert state.source == "cursor"

    def test_defaults(self):
        state = FileState(file_path="/tmp/x", source="gemini_cli")
        assert state.last_line_processed == 0
        assert state.content_hash == ""
        assert state.retry_count == 0
        assert state.last_error is None


class TestStateManager:
    @pytest.fixture
    def state_file(self, tmp_path: Path) -> Path:
        return tmp_path / "state.json"

    @pytest.fixture
    def mgr(self, state_file: Path) -> StateManager:
        return StateManager(state_file=state_file)

    def test_load_empty(self, mgr: StateManager):
        mgr.load()
        assert mgr.all_states() == {}

    def test_set_and_get(self, mgr: StateManager):
        mgr.load()
        state = FileState(file_path="/tmp/a.jsonl", source="claude_code")
        mgr.set_state(state)
        assert mgr.get_state("/tmp/a.jsonl") is state

    def test_save_and_reload(self, state_file: Path):
        mgr1 = StateManager(state_file=state_file)
        mgr1.load()
        mgr1.set_state(
            FileState(
                file_path="/tmp/test.jsonl",
                source="claude_code",
                last_line_processed=10,
            )
        )
        mgr1.save()

        # Reload from disk
        mgr2 = StateManager(state_file=state_file)
        mgr2.load()
        restored = mgr2.get_state("/tmp/test.jsonl")
        assert restored is not None
        assert restored.last_line_processed == 10
        assert restored.source == "claude_code"

    def test_save_is_atomic(self, state_file: Path, mgr: StateManager):
        mgr.load()
        mgr.set_state(FileState(file_path="/tmp/x", source="cursor"))
        mgr.save()

        # Verify JSON is valid
        data = json.loads(state_file.read_text())
        assert "files" in data
        assert "/tmp/x" in data["files"]

    def test_save_skips_when_not_dirty(self, state_file: Path, mgr: StateManager):
        mgr.load()
        mgr.save()
        # File should not be created if nothing changed
        assert not state_file.exists()

    def test_remove_state(self, mgr: StateManager):
        mgr.load()
        mgr.set_state(FileState(file_path="/tmp/a", source="cursor"))
        mgr.set_state(FileState(file_path="/tmp/b", source="cursor"))
        mgr.remove_state("/tmp/a")
        assert mgr.get_state("/tmp/a") is None
        assert mgr.get_state("/tmp/b") is not None

    def test_load_corrupted_file(self, state_file: Path, mgr: StateManager):
        state_file.write_text("not valid json")
        mgr.load()
        assert mgr.all_states() == {}

    def test_reset_state(self, mgr: StateManager):
        mgr.load()
        mgr.set_state(FileState(file_path="/tmp/a", source="claude_code", last_line_processed=50))
        mgr.set_state(FileState(file_path="/tmp/b", source="cursor", content_hash="abc123"))
        mgr.reset_state("/tmp/a")
        assert mgr.get_state("/tmp/a") is None
        assert mgr.get_state("/tmp/b") is not None

    def test_reset_state_nonexistent_is_noop(self, mgr: StateManager):
        mgr.load()
        mgr.reset_state("/tmp/does-not-exist")
        assert mgr.all_states() == {}

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "state.json"
        mgr = StateManager(state_file=nested)
        mgr.load()
        mgr.set_state(FileState(file_path="/tmp/x", source="cursor"))
        mgr.save()
        assert nested.exists()
