# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for FileWatcher glob caching."""

import os
import time

import pytest

from opentrace.daemon.config import DaemonConfig
from opentrace.daemon.state import StateManager
from opentrace.daemon.watcher import FileWatcher


@pytest.fixture
def tmp_config(tmp_path):
    """DaemonConfig with short glob_refresh_interval for testing."""
    return DaemonConfig(
        base_dir=tmp_path / ".quickcall-opentrace",
        poll_interval=1.0,
        glob_refresh_interval=2.0,
        ingest_url="http://localhost:19777/ingest",
    )


@pytest.fixture
def state_mgr(tmp_config):
    tmp_config.base_dir.mkdir(parents=True, exist_ok=True)
    return StateManager(state_file=tmp_config.state_file)


@pytest.fixture
def watcher(tmp_config, state_mgr):
    return FileWatcher(tmp_config, state_mgr)


class TestGlobCache:
    def test_cache_returns_same_results_within_ttl(self, watcher, tmp_path):
        """Within TTL and no mtime change, cache should return stale results."""
        test_dir = tmp_path / "test-project"
        test_dir.mkdir()
        (test_dir / "session.jsonl").write_text('{"test": true}\n')

        pattern = str(test_dir / "*.jsonl")

        paths1 = watcher._get_paths_cached(pattern)
        assert len(paths1) == 1

        # Add a file but fake the parent mtime to be unchanged
        (test_dir / "session2.jsonl").write_text('{"test": true}\n')
        # Restore parent mtime to cached value so cache thinks nothing changed
        cached_mtime = watcher._parent_mtimes.get(str(test_dir))
        if cached_mtime is not None:
            os.utime(str(test_dir), (cached_mtime, cached_mtime))

        paths2 = watcher._get_paths_cached(pattern)
        # Cache should return stale result (1 file) since mtime unchanged
        assert len(paths2) == 1

    def test_cache_invalidates_after_ttl(self, watcher, tmp_path):
        """Glob cache should expire after glob_refresh_interval."""
        test_dir = tmp_path / "test-project"
        test_dir.mkdir()
        (test_dir / "session.jsonl").write_text('{"test": true}\n')

        pattern = str(test_dir / "*.jsonl")

        paths1 = watcher._get_paths_cached(pattern)
        assert len(paths1) == 1

        # Add a second file
        (test_dir / "session2.jsonl").write_text('{"test": true}\n')

        # Manually expire the cache
        cached = watcher._glob_cache[pattern]
        watcher._glob_cache[pattern] = (cached[0] - 100, cached[1])

        # Now it should re-glob regardless of mtime
        paths2 = watcher._get_paths_cached(pattern)
        assert len(paths2) == 2

    def test_cache_invalidates_on_parent_mtime_change(self, watcher, tmp_path):
        """Cache should invalidate when parent directory mtime changes."""
        test_dir = tmp_path / "test-project"
        test_dir.mkdir()
        (test_dir / "a.jsonl").write_text("{}\n")

        pattern = str(test_dir / "*.jsonl")
        paths1 = watcher._get_paths_cached(pattern)
        assert len(paths1) == 1

        # Add a new file and force parent mtime forward to guarantee invalidation
        (test_dir / "b.jsonl").write_text("{}\n")
        future_mtime = time.time() + 10
        os.utime(str(test_dir), (future_mtime, future_mtime))

        paths2 = watcher._get_paths_cached(pattern)
        assert len(paths2) == 2

    def test_empty_glob_is_cached(self, watcher, tmp_path):
        """Empty glob results should also be cached."""
        pattern = str(tmp_path / "nonexistent" / "*.jsonl")
        paths = watcher._get_paths_cached(pattern)
        assert paths == []
        assert pattern in watcher._glob_cache
