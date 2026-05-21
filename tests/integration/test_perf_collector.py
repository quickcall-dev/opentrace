# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Performance regression tests for the daemon collector pipeline.

Uses REAL session files from the local machine to catch CPU regressions.
These files are NOT committed to git — tests are skipped in CI or when
files are missing.

Test data paths (gitignored):
  - Claude Code JSONL: ~/.claude/projects/-Users-test-work-opentrace/81f2f055-*.jsonl
  - Cursor vscdb:      ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb

WHY these tests exist:
  Issue #95 — daemon CPU spikes up to 42% on dev machines.
  Root cause was scan_session_timestamps() parsing ~2000 JSON blobs from
  Cursor's 569MB state.vscdb every 10-second poll cycle. These tests ensure
  we never regress.
"""


import cProfile
import io
import json
import os
import pstats
import time
from pathlib import Path

import pytest

from opentrace.daemon.collector import collect_file
from opentrace.daemon.pusher import _serialize_message
from opentrace.daemon.state import FileState
from opentrace.daemon.watcher import ChangedFile
from opentrace.utils.vscdb import scan_session_timestamps

# ---------------------------------------------------------------------------
# Real file paths for local performance testing
# ---------------------------------------------------------------------------
_HOME = str(Path.home())

# The Claude session that triggered issue #95 — 16MB / 3362 lines
_CLAUDE_SESSION = os.path.join(
    _HOME,
    ".claude/projects/-Users-test-work-opentrace",
    "81f2f055-ad61-45b6-b303-8f55a5de24a1.jsonl",
)

# Cursor's global state database — 569MB with ~2000 composerData entries
_CURSOR_VSCDB = os.path.join(
    _HOME,
    "Library/Application Support/Cursor/User/globalStorage/state.vscdb",
)

# Any Claude session JSONL under the trace project
_CLAUDE_PROJECT_DIR = os.path.join(
    _HOME,
    ".claude/projects/-Users-test-work-opentrace",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _skip_if_missing(path: str) -> None:
    if not os.path.exists(path):
        pytest.skip(f"Test data not found: {path}")


def _find_largest_claude_session() -> str | None:
    """Find the largest Claude JSONL in the trace project dir."""
    if not os.path.isdir(_CLAUDE_PROJECT_DIR):
        return None
    jsonl_files = [
        os.path.join(_CLAUDE_PROJECT_DIR, f)
        for f in os.listdir(_CLAUDE_PROJECT_DIR)
        if f.endswith(".jsonl")
    ]
    if not jsonl_files:
        return None
    return max(jsonl_files, key=os.path.getsize)


def _profile(func, *args, **kwargs):
    """Run func under cProfile, return (result, elapsed, profile_text).

    Profile text shows top 15 functions by self-time — the actual CPU hotspots.
    """
    profiler = cProfile.Profile()
    start = time.perf_counter()
    profiler.enable()
    result = func(*args, **kwargs)
    profiler.disable()
    elapsed = time.perf_counter() - start

    buf = io.StringIO()
    ps = pstats.Stats(profiler, stream=buf)
    ps.sort_stats("tottime")
    ps.print_stats(15)
    profile_text = buf.getvalue()

    return result, elapsed, profile_text


# ---------------------------------------------------------------------------
# Claude Code collector performance
# ---------------------------------------------------------------------------

class TestClaudeCollectorPerf:
    """Performance tests for Claude Code JSONL collection."""

    def _collect_full_session(self, session_path: str):
        """Run the full collector pipeline on a Claude session file."""

        stat = os.stat(session_path)
        changed = ChangedFile(
            path=session_path,
            source="claude_code",
            mtime=stat.st_mtime,
            size=stat.st_size,
        )
        return collect_file(
            changed,
            existing_state=None,
            device_name="perf-test",
            device_id="perf-test-device",
            global_email="test@test.com",
            global_name="Test",
            org="test",
        )

    def test_full_session_collection_time(self):
        """Collecting the full 16MB/3362-line session must complete in <5s.

        This covers: file read + JSON parse + transform + context attachment.
        Regression baseline (v0.4.46): ~600ms for this file.
        Threshold set at 5s to allow variance but catch O(n²) regressions.
        """
        _skip_if_missing(_CLAUDE_SESSION)

        result, elapsed, profile = _profile(
            self._collect_full_session, _CLAUDE_SESSION
        )

        assert result.messages, "Should produce messages from real session"
        assert len(result.messages) > 100, (
            f"Expected 100+ messages, got {len(result.messages)}"
        )

        size_kb = os.path.getsize(_CLAUDE_SESSION) / 1024
        print(
            f"\n  Claude collect: {elapsed:.3f}s, "
            f"{len(result.messages)} msgs, {size_kb:.0f}KB"
        )
        print(f"\n  Profile (top 15 by self-time):\n{profile}")

        assert elapsed < 5.0, (
            f"Claude collection took {elapsed:.2f}s (threshold 5s) — "
            f"possible regression.\n\nProfile:\n{profile}"
        )

    def test_largest_session_collection_time(self):
        """Collecting the largest available session must complete in <10s."""
        path = _find_largest_claude_session()
        if path is None:
            pytest.skip("No Claude sessions found")

        result, elapsed, profile = _profile(
            self._collect_full_session, path
        )

        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(
            f"\n  Largest session: {elapsed:.3f}s, "
            f"{len(result.messages)} msgs, {size_mb:.1f}MB"
        )
        print(f"\n  Profile (top 15 by self-time):\n{profile}")

        assert elapsed < 10.0, (
            f"Largest session ({size_mb:.1f}MB) took {elapsed:.2f}s "
            f"(threshold 10s).\n\nProfile:\n{profile}"
        )

    def test_incremental_collection_skips_unchanged(self):
        """When file size hasn't changed, collector must return in <1ms."""
        _skip_if_missing(_CLAUDE_SESSION)


        stat = os.stat(_CLAUDE_SESSION)
        changed = ChangedFile(
            path=_CLAUDE_SESSION,
            source="claude_code",
            mtime=stat.st_mtime,
            size=stat.st_size,
        )
        existing_state = FileState(
            file_path=_CLAUDE_SESSION,
            source="claude_code",
            last_line_processed=9999,
            last_mtime=stat.st_mtime - 1,  # mtime changed (triggers check)
            last_size=stat.st_size,  # but size same (early exit)
            retry_count=0,
        )

        start = time.perf_counter()
        result = collect_file(changed, existing_state)
        elapsed = time.perf_counter() - start

        assert result.messages == [], "Should produce no messages (unchanged)"
        assert elapsed < 0.001, (
            f"Early-exit took {elapsed*1000:.2f}ms (threshold 1ms) — "
            f"early-exit optimization may be broken"
        )
        print(f"\n  Incremental skip: {elapsed*1000:.3f}ms")


# ---------------------------------------------------------------------------
# Cursor vscdb scanner performance — THE root cause of issue #95
# ---------------------------------------------------------------------------

class TestCursorVscdbPerf:
    """Performance tests for Cursor state.vscdb scanning.

    scan_session_timestamps() was the #1 CPU hotspot in the daemon:
    - 569MB database, ~2000 composerData entries
    - Each entry parsed with json.loads() every poll cycle
    - 16.1s self-time + 10s JSON parsing in a 90s profile
    - Called every 10 seconds = 22% sustained CPU

    These tests enforce time budgets so we catch regressions immediately.
    """

    def test_scan_session_timestamps_time(self):
        """scan_session_timestamps on the real 569MB vscdb must complete in <2s.

        Regression baseline (v0.4.46 BEFORE fix): ~4s per call.
        After fixing, this should be well under 2s.
        If this test fails, the daemon is burning ~20% CPU just scanning timestamps.
        """
        _skip_if_missing(_CURSOR_VSCDB)


        result, elapsed, profile = _profile(
            scan_session_timestamps, _CURSOR_VSCDB
        )

        assert isinstance(result, dict), "Should return dict"
        assert len(result) > 0, "Should find composerData entries"

        db_size_mb = os.path.getsize(_CURSOR_VSCDB) / (1024 * 1024)
        print(
            f"\n  vscdb scan: {elapsed:.3f}s, "
            f"{len(result)} composer entries, {db_size_mb:.0f}MB db"
        )
        print(f"\n  Profile (top 15 by self-time):\n{profile}")

        assert elapsed < 2.0, (
            f"scan_session_timestamps took {elapsed:.2f}s (threshold 2s) — "
            f"this is the root cause of issue #95 CPU spikes. "
            f"Found {len(result)} entries.\n\nProfile:\n{profile}"
        )

    def test_scan_session_timestamps_repeated_calls(self):
        """Repeated scans (simulating poll cycles) must not degrade.

        The daemon calls this every 10s. Run 3 consecutive calls and
        verify none exceed the budget.
        """
        _skip_if_missing(_CURSOR_VSCDB)


        times = []
        profiles = []
        for _ in range(3):
            result, elapsed, profile = _profile(
                scan_session_timestamps, _CURSOR_VSCDB
            )
            times.append(elapsed)
            profiles.append(profile)

        max_time = max(times)
        avg_time = sum(times) / len(times)
        print(
            f"\n  vscdb 3x scan: "
            f"avg={avg_time:.3f}s, max={max_time:.3f}s, "
            f"times={[f'{t:.3f}s' for t in times]}"
        )
        # Print profile of the slowest run
        worst_idx = times.index(max_time)
        print(f"\n  Slowest run profile:\n{profiles[worst_idx]}")

        assert max_time < 2.0, (
            f"Worst of 3 scans: {max_time:.2f}s (threshold 2s). "
            f"All times: {[f'{t:.2f}s' for t in times]}\n\n"
            f"Slowest run profile:\n{profiles[worst_idx]}"
        )

    def test_full_vscdb_collector_time(self):
        """Full vscdb collector (scan + diff + transform) on first run.

        First run = ALL sessions are "changed" (worst case).
        Budget: 30s (generous — scan alone is ~4s pre-fix, transform is heavy).
        """
        _skip_if_missing(_CURSOR_VSCDB)


        stat = os.stat(_CURSOR_VSCDB)
        changed = ChangedFile(
            path=_CURSOR_VSCDB,
            source="cursor_vscdb",
            mtime=stat.st_mtime,
            size=stat.st_size,
        )

        def _do_collect():
            return collect_file(
                changed,
                existing_state=None,
                device_name="perf-test",
                device_id="perf-test-device",
                global_email="test@test.com",
                global_name="Test",
                org="test",
            )

        result, elapsed, profile = _profile(_do_collect)

        print(
            f"\n  vscdb full collect: {elapsed:.3f}s, "
            f"{len(result.messages)} msgs"
        )
        print(f"\n  Profile (top 15 by self-time):\n{profile}")

        assert elapsed < 30.0, (
            f"Full vscdb collection took {elapsed:.2f}s (threshold 30s).\n\n"
            f"Profile:\n{profile}"
        )

    def test_vscdb_incremental_is_fast(self):
        """Incremental poll with no changes — the steady-state hot path.

        This is what runs every 10 seconds. It does scan_session_timestamps
        + diff. With no changed sessions, no transforms run.
        MUST be under 2s — this is the critical path for issue #95.
        """
        _skip_if_missing(_CURSOR_VSCDB)


        # First: get current timestamps (simulates prior state)
        timestamps = scan_session_timestamps(_CURSOR_VSCDB)
        stat = os.stat(_CURSOR_VSCDB)

        changed = ChangedFile(
            path=_CURSOR_VSCDB,
            source="cursor_vscdb",
            mtime=stat.st_mtime,
            size=stat.st_size,
        )
        existing_state = FileState(
            file_path=_CURSOR_VSCDB,
            source="cursor_vscdb",
            content_hash=json.dumps(timestamps),
            last_mtime=stat.st_mtime - 1,  # mtime changed (triggers scan)
            last_size=stat.st_size,
            retry_count=0,
        )

        def _do_incremental():
            return collect_file(changed, existing_state)

        result, elapsed, profile = _profile(_do_incremental)

        print(
            f"\n  vscdb incremental: {elapsed:.3f}s, "
            f"{len(result.messages)} msgs (should be 0 or near 0)"
        )
        print(f"\n  Profile (top 15 by self-time):\n{profile}")

        assert elapsed < 2.0, (
            f"Incremental vscdb poll took {elapsed:.2f}s (threshold 2s) — "
            f"scan_session_timestamps is still too slow.\n\n"
            f"Profile:\n{profile}"
        )


# ---------------------------------------------------------------------------
# Serialization performance (pusher hot path)
# ---------------------------------------------------------------------------

class TestSerializationPerf:
    """Performance tests for message serialization (pusher path)."""

    def test_serialize_500_messages(self):
        """Serializing 500 NormalizedMessages must complete in <500ms.

        The pusher calls dataclasses.asdict() + json.dumps on every message.
        Regression baseline (v0.4.46): ~41ms for 500 messages.
        """
        _skip_if_missing(_CLAUDE_SESSION)


        stat = os.stat(_CLAUDE_SESSION)
        changed = ChangedFile(
            path=_CLAUDE_SESSION,
            source="claude_code",
            mtime=stat.st_mtime,
            size=stat.st_size,
        )
        result = collect_file(
            changed,
            existing_state=None,
            device_name="perf-test",
            device_id="perf-test-device",
        )

        msgs = result.messages[:500]
        assert len(msgs) >= 100, f"Need 100+ messages, got {len(msgs)}"

        def _do_serialize():
            serialized = [_serialize_message(m) for m in msgs]
            return json.dumps(serialized).encode("utf-8")

        payload, elapsed, profile = _profile(_do_serialize)

        print(
            f"\n  Serialize {len(msgs)} msgs: {elapsed*1000:.1f}ms, "
            f"payload {len(payload)/1024:.0f}KB"
        )
        print(f"\n  Profile (top 15 by self-time):\n{profile}")

        assert elapsed < 0.5, (
            f"Serializing {len(msgs)} messages took {elapsed*1000:.0f}ms "
            f"(threshold 500ms).\n\nProfile:\n{profile}"
        )
