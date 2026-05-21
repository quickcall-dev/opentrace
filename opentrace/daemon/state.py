# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""File processing state management with atomic writes."""


import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("quickcall.state")


@dataclass
class FileState:
    """Tracks processing state for a single file."""

    file_path: str
    source: str  # "claude_code", "codex_cli", "gemini_cli", "cursor"

    # For JSONL line-resume
    last_line_processed: int = 0

    # For hash-based change detection (JSON/text files)
    content_hash: str = ""

    # Error tracking
    retry_count: int = 0
    last_error: str | None = None

    # File metadata at last processing
    last_mtime: float = 0.0
    last_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileState":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class StateManager:
    """Manages file processing state, persisted as JSON on disk."""

    state_file: Path
    _states: dict[str, FileState] = field(default_factory=dict, repr=False)
    _dirty: bool = field(default=False, repr=False)

    def load(self) -> None:
        """Load state from disk."""
        if not self.state_file.exists():
            self._states = {}
            return
        try:
            data = json.loads(self.state_file.read_text())
            self._states = {
                k: FileState.from_dict(v) for k, v in data.get("files", {}).items()
            }
        except (json.JSONDecodeError, KeyError):
            self._states = {}

    def save(self) -> None:
        """Atomically write state to disk via tempfile + rename."""
        if not self._dirty:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "files": {k: v.to_dict() for k, v in self._states.items()},
        }
        fd, tmp_path = tempfile.mkstemp(
            dir=self.state_file.parent, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, self.state_file)
            self._dirty = False
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get_state(self, file_path: str) -> FileState | None:
        """Get state for a file, or None if not tracked."""
        return self._states.get(file_path)

    def set_state(self, state: FileState) -> None:
        """Update state for a file."""
        self._states[state.file_path] = state
        self._dirty = True

    def reset_state(self, file_path: str) -> None:
        """Remove a file's state so it gets re-processed from scratch."""
        if file_path in self._states:
            del self._states[file_path]
            self._dirty = True

    # Alias for backwards compatibility with tests
    remove_state = reset_state

    def reset_all(self) -> int:
        """Clear all file states. Returns the number of entries cleared."""
        count = len(self._states)
        if count > 0:
            self._states.clear()
            self._dirty = True
        return count

    def reset_by_source(self, source: str) -> int:
        """Clear state entries matching a given source. Returns count removed."""
        to_remove = [fp for fp, fs in self._states.items() if fs.source == source]
        for fp in to_remove:
            del self._states[fp]
        if to_remove:
            self._dirty = True
        return len(to_remove)

    def reset_since(self, cutoff: str) -> int:
        """Clear entries for files with last_mtime after cutoff (ISO date string).

        Uses FileState.last_mtime (epoch) compared against the cutoff date.
        Returns count removed.
        """
        try:
            cutoff_dt = datetime.fromisoformat(cutoff)
            if cutoff_dt.tzinfo is None:
                cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
            cutoff_epoch = cutoff_dt.timestamp()
        except ValueError:
            return 0

        to_remove = [
            fp for fp, fs in self._states.items()
            if fs.last_mtime >= cutoff_epoch
        ]
        for fp in to_remove:
            del self._states[fp]
        if to_remove:
            self._dirty = True
        return len(to_remove)

    def all_states(self) -> dict[str, FileState]:
        """Return all tracked file states."""
        return dict(self._states)

    def prune_missing_files(self) -> int:
        """Remove state entries for files that no longer exist on disk."""
        to_remove = [fp for fp in self._states if not os.path.exists(fp)]
        for fp in to_remove:
            del self._states[fp]
        if to_remove:
            self._dirty = True
            logger.info("Pruned %d stale state entry(ies)", len(to_remove))
        return len(to_remove)
