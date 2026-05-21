# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for Daemon.run() and _poll_cycle() — the main daemon loop."""


import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from opentrace.daemon.pusher import Pusher

from opentrace.daemon.collector import CollectResult
from opentrace.daemon.config import DaemonConfig
from opentrace.daemon.main import Daemon
from opentrace.daemon.state import FileState
from opentrace.daemon.watcher import ChangedFile

from tests.helpers import make_message


@pytest.fixture
def tmp_config(tmp_path: Path) -> DaemonConfig:
    return DaemonConfig(
        base_dir=tmp_path,
        ingest_url="http://127.0.0.1:19999/ingest",
        poll_interval=0.01,
        batch_size=5,
    )


@pytest.fixture
def daemon(tmp_config: DaemonConfig) -> Daemon:
    d = Daemon(config=tmp_config)
    d.state_mgr.load()
    d.device_name = "test-host"
    d.global_email = "test@example.com"
    d.global_name = "Test User"
    return d


class TestPollCycle:
    """Tests for Daemon._poll_cycle()."""

    def test_poll_cycle_no_changed_files(self, daemon: Daemon):
        """When no files have changed, poll_cycle saves state but does nothing else."""
        daemon.watcher.get_changed_files = MagicMock(return_value=[])
        daemon._poll_cycle()
        daemon.watcher.get_changed_files.assert_called_once()

    @patch("opentrace.daemon.main.collect_file")
    def test_poll_cycle_collects_and_pushes(self, mock_collect, daemon: Daemon):
        """Changed files are collected and pushed."""
        changed = ChangedFile(path="/tmp/a.jsonl", source="claude_code", mtime=1.0, size=100)
        daemon.watcher.get_changed_files = MagicMock(return_value=[changed])

        msgs = [make_message(id=f"msg-{i}") for i in range(3)]
        new_state = FileState(file_path="/tmp/a.jsonl", source="claude_code", last_line_processed=10)
        mock_collect.return_value = CollectResult(messages=msgs, new_state=new_state)

        daemon.pusher.push = MagicMock(return_value=True)
        daemon._poll_cycle()

        mock_collect.assert_called_once()
        daemon.pusher.push.assert_called_once_with(msgs)
        assert daemon.state_mgr.get_state("/tmp/a.jsonl") is not None
        assert daemon.state_mgr.get_state("/tmp/a.jsonl").last_line_processed == 10

    @patch("opentrace.daemon.main.collect_file")
    def test_poll_cycle_handles_collect_error(self, mock_collect, daemon: Daemon):
        """When collect_file raises, the error is logged and retry count incremented."""
        changed = ChangedFile(path="/tmp/a.jsonl", source="claude_code", mtime=1.0, size=100)
        daemon.watcher.get_changed_files = MagicMock(return_value=[changed])

        existing = FileState(file_path="/tmp/a.jsonl", source="claude_code", last_line_processed=5)
        daemon.state_mgr.set_state(existing)

        mock_collect.side_effect = RuntimeError("parse error")
        daemon._poll_cycle()

        state = daemon.state_mgr.get_state("/tmp/a.jsonl")
        assert state.retry_count == 1
        assert state.last_error == "parse error"

    @patch("opentrace.daemon.main.collect_file")
    def test_poll_cycle_empty_messages_still_updates_state(self, mock_collect, daemon: Daemon):
        """When collect returns no messages, state is still updated."""
        changed = ChangedFile(path="/tmp/a.jsonl", source="claude_code", mtime=1.0, size=100)
        daemon.watcher.get_changed_files = MagicMock(return_value=[changed])

        new_state = FileState(file_path="/tmp/a.jsonl", source="claude_code", last_line_processed=5)
        mock_collect.return_value = CollectResult(messages=[], new_state=new_state)

        daemon.pusher.push = MagicMock()
        daemon._poll_cycle()

        daemon.pusher.push.assert_not_called()
        assert daemon.state_mgr.get_state("/tmp/a.jsonl").last_line_processed == 5

    @patch("opentrace.daemon.main.collect_file")
    def test_poll_cycle_batching(self, mock_collect, daemon: Daemon):
        """Messages exceeding batch_size are pushed in multiple batches."""

        daemon.config.batch_size = 3
        changed = ChangedFile(path="/tmp/a.jsonl", source="claude_code", mtime=1.0, size=100)
        daemon.watcher.get_changed_files = MagicMock(return_value=[changed])

        msgs = [make_message(id=f"msg-{i}") for i in range(7)]
        new_state = FileState(file_path="/tmp/a.jsonl", source="claude_code", last_line_processed=10)
        mock_collect.return_value = CollectResult(messages=msgs, new_state=new_state)

        daemon.pusher.push = MagicMock(return_value=True)
        original_prop = Pusher.current_backoff
        try:
            type(daemon.pusher).current_backoff = property(lambda self: 0)
            daemon._poll_cycle()
        finally:
            Pusher.current_backoff = original_prop

        # 7 messages, batch_size=3 → 3 pushes (3, 3, 1)
        assert daemon.pusher.push.call_count == 3
        call_sizes = [len(c.args[0]) for c in daemon.pusher.push.call_args_list]
        assert call_sizes == [3, 3, 1]

    @patch("opentrace.daemon.main.collect_file")
    def test_poll_cycle_respects_shutdown(self, mock_collect, daemon: Daemon):
        """When shutdown is set, poll_cycle stops processing files."""
        changed1 = ChangedFile(path="/tmp/a.jsonl", source="claude_code", mtime=1.0, size=100)
        changed2 = ChangedFile(path="/tmp/b.jsonl", source="claude_code", mtime=1.0, size=100)
        daemon.watcher.get_changed_files = MagicMock(return_value=[changed1, changed2])

        daemon._shutdown = True
        daemon._poll_cycle()

        mock_collect.assert_not_called()


    @patch("opentrace.daemon.main.collect_file")
    def test_poll_cycle_partial_push_failure(self, mock_collect, daemon: Daemon):
        """When push fails mid-batch, only files before the failure have state advanced."""
        daemon.config.batch_size = 3

        changed_a = ChangedFile(path="/tmp/a.jsonl", source="claude_code", mtime=1.0, size=50)
        changed_b = ChangedFile(path="/tmp/b.jsonl", source="claude_code", mtime=1.0, size=100)
        changed_c = ChangedFile(path="/tmp/c.jsonl", source="claude_code", mtime=1.0, size=150)
        daemon.watcher.get_changed_files = MagicMock(return_value=[changed_a, changed_b, changed_c])

        msgs_a = [make_message(id=f"a-{i}") for i in range(2)]
        msgs_b = [make_message(id=f"b-{i}") for i in range(2)]
        msgs_c = [make_message(id=f"c-{i}") for i in range(2)]

        state_a = FileState(file_path="/tmp/a.jsonl", source="claude_code", last_line_processed=10)
        state_b = FileState(file_path="/tmp/b.jsonl", source="claude_code", last_line_processed=20)
        state_c = FileState(file_path="/tmp/c.jsonl", source="claude_code", last_line_processed=30)

        mock_collect.side_effect = [
            CollectResult(messages=msgs_a, new_state=state_a),
            CollectResult(messages=msgs_b, new_state=state_b),
            CollectResult(messages=msgs_c, new_state=state_c),
        ]

        # batch_size=3: first batch = a(2) + b(1), second batch = b(1) + c(2)
        # Fail on second batch — file b and c should NOT have state advanced
        push_calls = [0]

        def mock_push(msgs):
            push_calls[0] += 1
            if push_calls[0] == 1:
                return True  # first batch succeeds
            return False  # second batch fails

        daemon.pusher.push = MagicMock(side_effect=mock_push)
        daemon._poll_cycle()

        # File A: all 2 messages were in the first batch → state advanced
        assert daemon.state_mgr.get_state("/tmp/a.jsonl") is not None
        assert daemon.state_mgr.get_state("/tmp/a.jsonl").last_line_processed == 10

        # File B: had messages in both batches → NOT advanced (some in failed batch)
        assert daemon.state_mgr.get_state("/tmp/b.jsonl") is None

        # File C: all messages in failed batch → NOT advanced
        assert daemon.state_mgr.get_state("/tmp/c.jsonl") is None

    @patch("opentrace.daemon.main.collect_file")
    def test_poll_cycle_max_accumulate_cap(self, mock_collect, daemon: Daemon):
        """When _MAX_ACCUMULATE is reached, remaining files are deferred."""
        daemon._MAX_ACCUMULATE = 3

        files = [
            ChangedFile(path=f"/tmp/{c}.jsonl", source="claude_code", mtime=1.0, size=i * 50)
            for i, c in enumerate(["a", "b", "c", "d"])
        ]
        daemon.watcher.get_changed_files = MagicMock(return_value=files)

        def make_result(path, count):
            msgs = [make_message(id=f"{path}-{i}") for i in range(count)]
            state = FileState(file_path=path, source="claude_code", last_line_processed=count)
            return CollectResult(messages=msgs, new_state=state)

        # Each file produces 2 messages; cap is 3, so after file B (4 total) we stop
        mock_collect.side_effect = [
            make_result("/tmp/a.jsonl", 2),
            make_result("/tmp/b.jsonl", 2),
            make_result("/tmp/c.jsonl", 2),
            make_result("/tmp/d.jsonl", 2),
        ]

        daemon.pusher.push = MagicMock(return_value=True)
        daemon._poll_cycle()

        # Only 2 files should have been collected (4 msgs >= cap of 3)
        assert mock_collect.call_count == 2
        assert daemon.state_mgr.get_state("/tmp/a.jsonl") is not None
        assert daemon.state_mgr.get_state("/tmp/b.jsonl") is not None
        assert daemon.state_mgr.get_state("/tmp/c.jsonl") is None
        assert daemon.state_mgr.get_state("/tmp/d.jsonl") is None


class TestDaemonRun:
    """Tests for Daemon.run() lifecycle."""

    @patch("opentrace.daemon.main.resolve_global_identity", return_value=("test@test.com", "Test"))
    @patch("opentrace.daemon.main.socket")
    def test_run_writes_pid_and_cleans_up(self, mock_socket, mock_identity, tmp_config: DaemonConfig):
        """run() writes PID file and cleans up on exit."""
        mock_socket.gethostname.return_value = "test-host"
        daemon = Daemon(config=tmp_config)

        # Make it exit immediately
        daemon._poll_cycle = MagicMock(side_effect=lambda: setattr(daemon, '_shutdown', True))
        daemon._sleep = MagicMock()

        daemon.run()

        # PID file should be cleaned up
        assert not tmp_config.pid_file.exists()
        assert daemon.device_name == "test-host"
        assert daemon.global_email == "test@test.com"

    @patch("opentrace.daemon.main.resolve_global_identity", return_value=(None, None))
    @patch("opentrace.daemon.main.socket")
    def test_run_calls_reconcile(self, mock_socket, mock_identity, tmp_config: DaemonConfig):
        """run() calls _reconcile before entering the loop."""
        mock_socket.gethostname.return_value = "host"
        daemon = Daemon(config=tmp_config)
        daemon._reconcile = MagicMock()
        daemon._poll_cycle = MagicMock(side_effect=lambda: setattr(daemon, '_shutdown', True))
        daemon._sleep = MagicMock()

        daemon.run()

        daemon._reconcile.assert_called_once()


class TestDaemonSleep:
    """Tests for Daemon._sleep()."""

    def test_sleep_respects_shutdown(self, daemon: Daemon):
        """_sleep exits early when shutdown is set."""
        daemon._shutdown = True
        daemon._sleep(10.0)  # should return instantly

    def test_sleep_for_short_duration(self, daemon: Daemon):
        """_sleep completes for very short durations."""
        start = time.monotonic()
        daemon._sleep(0.05)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0


class TestDaemonSignals:
    """Tests for signal handling."""

    def test_handle_signal_sets_shutdown(self, daemon: Daemon):
        assert daemon._shutdown is False
        daemon._handle_signal(15, None)
        assert daemon._shutdown is True


class TestTruncateErrLog:
    """Tests for _truncate_err_log() — keeps opentrace.err bounded."""

    def test_truncates_large_err_file(self, daemon: Daemon, tmp_config: DaemonConfig):
        err_file = tmp_config.base_dir / "quickcall.err"
        err_file.write_text("\n".join(f"line {i}" for i in range(2000)) + "\n")

        daemon._truncate_err_log()

        lines = err_file.read_text().splitlines()
        assert len(lines) == 1000
        assert lines[0] == "line 1000"
        assert lines[-1] == "line 1999"

    def test_noop_when_under_limit(self, daemon: Daemon, tmp_config: DaemonConfig):
        err_file = tmp_config.base_dir / "quickcall.err"
        err_file.write_text("line 1\nline 2\nline 3\n")

        daemon._truncate_err_log()

        assert err_file.read_text() == "line 1\nline 2\nline 3\n"

    def test_noop_when_no_err_file(self, daemon: Daemon, tmp_config: DaemonConfig):
        daemon._truncate_err_log()  # should not raise

    def test_keeps_exactly_max_lines(self, daemon: Daemon, tmp_config: DaemonConfig):
        err_file = tmp_config.base_dir / "quickcall.err"
        err_file.write_text("\n".join(f"line {i}" for i in range(1000)) + "\n")

        daemon._truncate_err_log()

        # Exactly at limit — should not truncate
        lines = err_file.read_text().splitlines()
        assert len(lines) == 1000
        assert lines[0] == "line 0"

