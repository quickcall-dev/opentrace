# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for daemon HTTP pusher."""

import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from unittest.mock import patch

from opentrace.daemon.pusher import _MAX_PAYLOAD_BYTES

import pytest

from opentrace.daemon.config import DaemonConfig
from opentrace.daemon.pusher import Pusher, _serialize_message

from tests.helpers import make_message


class TestSerializeMessage:
    def test_basic_serialization(self):
        msg = make_message()
        d = _serialize_message(msg)
        assert d["id"] == "msg-1"
        assert d["source"] == "claude_code"
        assert d["content"] == "hello"
        # None fields should be removed
        assert "thinking" not in d
        assert "tool_call" not in d

    def test_json_roundtrip(self):
        msg = make_message()
        d = _serialize_message(msg)
        s = json.dumps(d)
        restored = json.loads(s)
        assert restored["id"] == "msg-1"


class TestPusher:
    @pytest.fixture
    def config(self) -> DaemonConfig:
        return DaemonConfig(
            ingest_url="http://localhost:19999/ingest",
            retry_backoff_base=0.01,
            retry_backoff_max=0.1,
            retry_queue_max=100,
            batch_size=10,
        )

    @pytest.fixture
    def pusher(self, config: DaemonConfig) -> Pusher:
        return Pusher(config=config)

    def test_push_empty_list(self, pusher: Pusher):
        assert pusher.push([]) is True

    def test_push_failure_queues_messages(self, pusher: Pusher):
        msgs = [make_message(id=f"msg-{i}") for i in range(5)]
        # No server running, so push should fail
        result = pusher.push(msgs)
        assert result is False
        assert pusher.queue_size == 5
        assert pusher.has_queued()

    def test_backoff_increases(self, pusher: Pusher):
        msgs = [make_message()]
        pusher.push(msgs)
        backoff1 = pusher.current_backoff

        pusher.push(msgs)
        backoff2 = pusher.current_backoff

        assert backoff2 > backoff1

    def test_queue_bounded(self, pusher: Pusher):
        pusher.config.retry_queue_max = 5
        msgs = [make_message(id=f"msg-{i}") for i in range(10)]
        pusher.push(msgs)
        assert pusher.queue_size == 5  # oldest 5 dropped

    def test_success_resets_backoff(self, pusher: Pusher):
        # Simulate failure
        msgs = [make_message()]
        pusher.push(msgs)
        assert pusher.current_backoff > 0

        # Reset on success
        pusher._on_success()
        assert pusher.current_backoff == 0.0
        assert pusher._consecutive_failures == 0


class TestPusherWithServer:
    """Integration tests with a real HTTP server."""

    @pytest.fixture
    def server(self):
        received = []
        progress_received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                if self.path == "/api/file-progress-bulk":
                    progress_received.append(json.loads(body))
                else:
                    received.append(json.loads(body))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

            def log_message(self, format, *args):
                pass  # suppress logs

        srv = HTTPServer(("127.0.0.1", 0), Handler)
        port = srv.server_address[1]
        t = Thread(target=srv.serve_forever, daemon=True)
        t.start()
        yield port, received, progress_received
        srv.shutdown()

    def test_successful_push(self, server):
        port, received, _ = server
        config = DaemonConfig(ingest_url=f"http://127.0.0.1:{port}/ingest")
        pusher = Pusher(config=config)

        msgs = [make_message(id="msg-1"), make_message(id="msg-2")]
        result = pusher.push(msgs)
        assert result is True
        assert len(received) == 1
        assert len(received[0]) == 2

    def test_drains_queue_on_success(self, server):
        port, received, _ = server
        config = DaemonConfig(
            ingest_url=f"http://127.0.0.1:{port}/ingest",
            batch_size=5,
        )
        pusher = Pusher(config=config)

        # Pre-fill queue
        pusher._queue.extend(
            [_serialize_message(make_message(id=f"queued-{i}")) for i in range(3)]
        )

        # Push new messages — should also drain queue
        msgs = [make_message(id="new-1")]
        result = pusher.push(msgs)
        assert result is True
        assert len(received) == 2  # one for new, one for queued
        assert pusher.queue_size == 0

    def test_new_messages_sent_before_queued(self, server):
        """New messages are pushed first, then queued messages are drained (M2)."""
        port, received, _ = server
        config = DaemonConfig(
            ingest_url=f"http://127.0.0.1:{port}/ingest",
            batch_size=100,
        )
        pusher = Pusher(config=config)

        # Pre-fill queue with identifiable messages
        pusher._queue.extend(
            [_serialize_message(make_message(id=f"queued-{i}")) for i in range(2)]
        )

        # Push new messages
        msgs = [make_message(id="new-1"), make_message(id="new-2")]
        result = pusher.push(msgs)
        assert result is True
        assert len(received) == 2

        # First batch should be the new messages
        new_ids = [m["id"] for m in received[0]]
        assert new_ids == ["new-1", "new-2"]

        # Second batch should be the queued messages
        queued_ids = [m["id"] for m in received[1]]
        assert queued_ids == ["queued-0", "queued-1"]

    def test_drain_failure_requeues_messages(self, server):
        """If draining the queue fails, messages are re-queued (M2)."""
        port, received, _ = server
        config = DaemonConfig(
            ingest_url=f"http://127.0.0.1:{port}/ingest",
            batch_size=100,
        )
        pusher = Pusher(config=config)

        # Push succeeds for new messages
        msgs = [make_message(id="new-1")]
        result = pusher.push(msgs)
        assert result is True

        # Now pre-fill queue and make server unavailable for drain
        pusher._queue.extend(
            [_serialize_message(make_message(id=f"queued-{i}")) for i in range(3)]
        )

        # Patch _post_batch to fail only for the drain call
        original_post = pusher._post_batch
        call_count = [0]

        def patched_post(batch):
            call_count[0] += 1
            if call_count[0] == 2:  # fail on drain
                return False
            return original_post(batch)

        pusher._post_batch = patched_post
        msgs = [make_message(id="new-2")]
        pusher.push(msgs)

        # Queue should still have the messages since drain failed
        assert pusher.queue_size == 3

    def test_report_progress_bulk(self, server):
        port, _, progress_received = server
        config = DaemonConfig(ingest_url=f"http://127.0.0.1:{port}/ingest")
        pusher = Pusher(config=config)

        reports = [
            {"raw_file_path": "/tmp/a.jsonl", "source": "claude_code",
             "last_line_read": 150, "content_hash": "abc123"},
            {"raw_file_path": "/tmp/b.jsonl", "source": "claude_code",
             "last_line_read": 200, "content_hash": None},
        ]
        result = pusher.report_progress_bulk(reports)
        assert result is True
        assert len(progress_received) == 1
        assert len(progress_received[0]) == 2
        assert progress_received[0][0]["raw_file_path"] == "/tmp/a.jsonl"
        assert progress_received[0][1]["raw_file_path"] == "/tmp/b.jsonl"

    def test_report_progress_bulk_empty(self, server):
        port, _, progress_received = server
        config = DaemonConfig(ingest_url=f"http://127.0.0.1:{port}/ingest")
        pusher = Pusher(config=config)

        result = pusher.report_progress_bulk([])
        assert result is True
        assert len(progress_received) == 0  # no HTTP call made

    def test_report_progress_bulk_failure(self):
        config = DaemonConfig(ingest_url="http://127.0.0.1:19999/ingest")
        pusher = Pusher(config=config)

        result = pusher.report_progress_bulk([
            {"raw_file_path": "/tmp/a.jsonl", "source": "claude_code", "last_line_read": 100},
        ])
        assert result is False


class TestPusherRecovery:
    """Tests for backoff decay and queue drop recovery logic."""

    @pytest.fixture
    def config(self) -> DaemonConfig:
        return DaemonConfig(
            ingest_url="http://127.0.0.1:19999/ingest",
            retry_backoff_base=0.01,
            retry_backoff_max=0.1,
            retry_queue_max=10,
            retry_cooldown=0.1,  # very short for testing
            retry_timeout=0.1,
            batch_size=10,
        )

    @pytest.fixture
    def pusher(self, config: DaemonConfig) -> Pusher:
        return Pusher(config=config)

    @patch("opentrace.daemon.pusher.record_error")
    def test_backoff_decays_after_cooldown(self, mock_record_error, pusher: Pusher):
        """Backoff should decay to base value after cooldown period."""
        msgs = [make_message()]

        # Cause failures to build up backoff
        pusher.push(msgs)
        pusher.push(msgs)
        assert pusher._backoff > pusher.config.retry_backoff_base

        # Simulate time passing beyond cooldown
        pusher._last_failure_time = time.monotonic() - 1.0  # 1s ago, cooldown is 0.1s

        # Next push should decay backoff before sleeping
        pusher.push(msgs)
        # After the decay, backoff was reset to base, then failure re-calculated
        # The key check: consecutive_failures was reset to 1 before the push attempt
        # so backoff should be base * 2^0 = base (since it fails again and increments)
        assert pusher._backoff <= pusher.config.retry_backoff_base * 2

    @patch("opentrace.daemon.pusher.record_error")
    def test_queue_drop_on_persistent_failure(self, mock_record_error, pusher: Pusher):
        """Queue should be cleared when failures persist past timeout and queue is full."""
        # Fill queue to max
        for i in range(pusher.config.retry_queue_max):
            pusher._queue.append({"id": f"msg-{i}"})
        assert pusher.queue_size == pusher.config.retry_queue_max

        # Set up persistent failure state (past timeout)
        pusher._last_failure_time = time.monotonic() - 1.0  # past retry_timeout of 0.1s
        pusher._consecutive_failures = 5

        # Trigger _on_failure which should drop the queue
        pusher._on_failure(Exception("HTTP 503"))
        assert pusher.queue_size == 0

    @patch("opentrace.daemon.pusher.record_error")
    def test_queue_not_dropped_when_not_full(self, mock_record_error, pusher: Pusher):
        """Queue should NOT be dropped if it's not at max capacity."""
        # Partially fill queue
        for i in range(3):
            pusher._queue.append({"id": f"msg-{i}"})

        # Past timeout
        pusher._last_failure_time = time.monotonic() - 1.0
        pusher._consecutive_failures = 5

        pusher._on_failure(Exception("HTTP 503"))
        assert pusher.queue_size == 3  # not dropped

    @patch("opentrace.daemon.pusher.record_error")
    def test_backoff_no_decay_within_cooldown(self, mock_record_error, pusher: Pusher):
        """Backoff should NOT decay if cooldown hasn't elapsed."""
        msgs = [make_message()]

        # Cause failures
        pusher.push(msgs)
        pusher.push(msgs)
        high_backoff = pusher._backoff

        # Last failure is very recent (within cooldown)
        pusher._last_failure_time = time.monotonic()

        # Push again — backoff should not decay
        pusher.push(msgs)
        # Backoff should have increased or stayed same, not decayed
        assert pusher._backoff >= high_backoff or pusher._backoff == pusher.config.retry_backoff_max

    @patch("opentrace.daemon.pusher.record_error")
    def test_error_not_recorded_on_first_failure(self, mock_record_error, pusher: Pusher):
        """Transient failures (< 3 consecutive) should NOT record errors."""
        msgs = [make_message()]
        pusher.push(msgs)
        mock_record_error.assert_not_called()

    @patch("opentrace.daemon.pusher.record_error")
    def test_error_recorded_after_threshold(self, mock_record_error, pusher: Pusher):
        """Errors should be recorded after 3+ consecutive failures."""
        msgs = [make_message()]
        pusher.push(msgs)  # failure 1
        pusher.push(msgs)  # failure 2
        pusher.push(msgs)  # failure 3 — should record
        assert mock_record_error.call_count == 1


class TestPostBatchSplitting:
    """Tests for payload-size-aware batch splitting."""

    @pytest.fixture
    def server(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                received.append(json.loads(body))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

            def log_message(self, format, *args):
                pass

        srv = HTTPServer(("127.0.0.1", 0), Handler)
        port = srv.server_address[1]
        t = Thread(target=srv.serve_forever, daemon=True)
        t.start()
        yield port, received
        srv.shutdown()

    def test_splits_large_payload(self, server):
        """Batch exceeding 4MB is split into multiple smaller POSTs."""
        port, received = server
        config = DaemonConfig(ingest_url=f"http://127.0.0.1:{port}/ingest")
        pusher = Pusher(config=config)

        # Create messages with large content to exceed threshold
        big_content = "x" * 500_000  # 500KB each
        batch = [_serialize_message(make_message(id=f"msg-{i}", content=big_content))
                 for i in range(12)]  # ~6MB total

        result = pusher._post_batch(batch)
        assert result is True
        assert len(received) >= 2  # must have been split
        # All messages delivered
        all_ids = [m["id"] for req in received for m in req]
        assert sorted(all_ids) == sorted(f"msg-{i}" for i in range(12))

    def test_no_split_under_threshold(self, server):
        """Normal-sized batch sends a single POST."""
        port, received = server
        config = DaemonConfig(ingest_url=f"http://127.0.0.1:{port}/ingest")
        pusher = Pusher(config=config)

        batch = [_serialize_message(make_message(id=f"msg-{i}")) for i in range(5)]
        result = pusher._post_batch(batch)
        assert result is True
        assert len(received) == 1
        assert len(received[0]) == 5

    def test_split_partial_failure(self, server):
        """If second half fails, _post_batch returns False."""
        port, received = server
        config = DaemonConfig(ingest_url=f"http://127.0.0.1:{port}/ingest")
        pusher = Pusher(config=config)

        big_content = "x" * 500_000
        batch = [_serialize_message(make_message(id=f"msg-{i}", content=big_content))
                 for i in range(12)]

        # Track HTTP-level sends and fail on the second one
        http_count = [0]
        original_post = Pusher._post_batch

        def counting_post(self_inner, b):
            payload = json.dumps(b).encode("utf-8")
            if len(payload) > _MAX_PAYLOAD_BYTES and len(b) > 1:
                mid = len(b) // 2
                return counting_post(self_inner, b[:mid]) and counting_post(self_inner, b[mid:])
            http_count[0] += 1
            if http_count[0] == 2:
                return False
            return original_post(self_inner, b)

        pusher._post_batch = lambda b: counting_post(pusher, b)
        result = pusher._post_batch(batch)
        assert result is False
        # First leaf call succeeded
        assert len(received) >= 1

    def test_single_oversized_message(self, server):
        """Single message > 4MB is sent as-is (no infinite recursion)."""
        port, received = server
        config = DaemonConfig(ingest_url=f"http://127.0.0.1:{port}/ingest")
        pusher = Pusher(config=config)

        huge_content = "x" * (5 * 1024 * 1024)  # 5MB single message
        batch = [_serialize_message(make_message(id="huge-msg", content=huge_content))]

        result = pusher._post_batch(batch)
        assert result is True
        assert len(received) == 1
        assert received[0][0]["id"] == "huge-msg"
