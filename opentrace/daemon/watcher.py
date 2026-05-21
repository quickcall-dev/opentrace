# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""File discovery for coding agent session files."""


import glob
import os
import time
from dataclasses import dataclass
from pathlib import Path

from opentrace.daemon.config import DaemonConfig
from opentrace.daemon.state import StateManager
from opentrace.schemas.unified import SourceType


@dataclass
class ChangedFile:
    """A file that has changed since last processing."""

    path: str
    source: SourceType
    mtime: float
    size: int


class FileWatcher:
    """Discovers session files and detects changes."""

    def __init__(self, config: DaemonConfig, state_mgr: StateManager) -> None:
        self._config = config
        self._state_mgr = state_mgr
        self._home = str(Path.home())
        # Glob result cache: pattern -> (last_glob_time, file_paths)
        self._glob_cache: dict[str, tuple[float, list[str]]] = {}
        # Parent directory mtime cache for invalidation
        self._parent_mtimes: dict[str, float] = {}

    def get_changed_files(self) -> list[ChangedFile]:
        """Scan all source directories and return files that changed since last check."""
        changed: list[ChangedFile] = []
        source_globs: list[tuple[SourceType, str]] = [
            ("claude_code", self._config.claude_code_glob),
            ("codex_cli", self._config.codex_cli_glob),
            ("gemini_cli", self._config.gemini_cli_glob),
            ("cursor", self._config.cursor_glob),
            ("cursor_vscdb", self._config.cursor_vscdb_glob),
            ("pi", self._config.pi_glob),
        ]

        for source, pattern in source_globs:
            full_pattern = os.path.join(self._home, pattern)
            file_paths = self._get_paths_cached(full_pattern)
            for file_path in file_paths:
                cf = self._check_file(file_path, source)
                if cf is not None:
                    changed.append(cf)

        # When max_files is set, keep only the N most recently modified files.
        # Used in dev testing to avoid pushing all historical sessions.
        if self._config.max_files > 0 and len(changed) > self._config.max_files:
            changed.sort(key=lambda f: f.mtime, reverse=True)
            changed = changed[: self._config.max_files]

        return changed

    def _get_paths_cached(self, full_pattern: str) -> list[str]:
        """Return file paths for a glob pattern, using cache when possible.

        Re-globs if:
        - No cached result exists
        - More than glob_refresh_interval seconds since last glob
        - Any parent directory's mtime has changed (new/deleted files)
        """
        now = time.monotonic()
        cached = self._glob_cache.get(full_pattern)

        if cached is not None:
            last_time, paths = cached
            elapsed = now - last_time
            if elapsed < self._config.glob_refresh_interval:
                # Check if parent directories changed (cheap stat calls)
                if not self._parent_dirs_changed(full_pattern):
                    return paths

        # Full re-glob
        paths = glob.glob(full_pattern, recursive=True)
        self._glob_cache[full_pattern] = (now, paths)
        self._update_parent_mtimes(full_pattern, paths)
        return paths

    def _parent_dirs_changed(self, pattern: str) -> bool:
        """Check if any cached parent directory mtime changed."""
        for parent, old_mtime in list(self._parent_mtimes.items()):
            if not parent.startswith(os.path.dirname(pattern).split("*")[0]):
                continue
            try:
                current_mtime = os.stat(parent).st_mtime
                if current_mtime != old_mtime:
                    return True
            except OSError:
                return True  # directory gone, need re-glob
        return False

    def _update_parent_mtimes(self, pattern: str, paths: list[str]) -> None:
        """Cache mtime of parent directories for the given paths."""
        parents: set[str] = set()
        for p in paths:
            parents.add(os.path.dirname(p))
        # Also add the base dir from the pattern (catches empty dirs)
        base = os.path.dirname(pattern).split("*")[0].rstrip("/")
        if base and os.path.isdir(base):
            parents.add(base)

        for parent in parents:
            try:
                self._parent_mtimes[parent] = os.stat(parent).st_mtime
            except OSError:
                pass

    def _check_file(self, file_path: str, source: SourceType) -> ChangedFile | None:
        """Check if a single file has changed and is eligible for processing."""
        try:
            stat = os.stat(file_path)
        except OSError:
            return None

        size = stat.st_size
        mtime = stat.st_mtime

        # For SQLite sources, also check the WAL file — writes go there
        # and the main DB's mtime/size won't change until a checkpoint.
        _DB_SOURCES: set[SourceType] = {"cursor_vscdb"}
        if source in _DB_SOURCES:
            wal_path = file_path + "-wal"
            try:
                wal_stat = os.stat(wal_path)
                # Use the most recent mtime and combined size
                mtime = max(mtime, wal_stat.st_mtime)
                size = size + wal_stat.st_size
            except OSError:
                pass  # No WAL file — DB not in WAL mode or already checkpointed

        # Skip files over max size (except database sources that use SQL queries)
        if source not in _DB_SOURCES and size > self._config.max_file_size:
            return None

        # Skip empty files
        if size == 0:
            return None

        existing = self._state_mgr.get_state(file_path)
        if existing is not None:
            # Skip if file hasn't changed
            if existing.last_mtime == mtime and existing.last_size == size:
                return None
            # Skip if max retries exceeded (until file changes again)
            if (
                existing.retry_count >= self._config.max_retries_per_file
                and existing.last_mtime == mtime
            ):
                return None

        return ChangedFile(path=file_path, source=source, mtime=mtime, size=size)
