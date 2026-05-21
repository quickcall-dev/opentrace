# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for daemon diagnostics error ring buffer."""

import json
import time
from unittest.mock import patch

from opentrace.daemon.push_status import record_error, get_recent_errors


class TestErrorRingBuffer:
    """Test push_status error recording with tracebacks."""

    def test_record_and_read_errors(self, tmp_path):
        """Errors are stored individually (not deduped) with tracebacks."""
        status_file = tmp_path / "push_status.json"
        lock_file = tmp_path / "push_status.lock"

        with patch("opentrace.daemon.push_status.PUSH_STATUS_FILE", status_file), \
             patch("opentrace.daemon.push_status._LOCK_FILE", lock_file):
            record_error("HTTP 503: Service Unavailable", traceback_text="Traceback:\n  File foo.py\nHTTPError: 503")
            record_error("HTTP 503: Service Unavailable", traceback_text="Traceback:\n  File foo.py\nHTTPError: 503")
            record_error("Connection refused")

            errors = get_recent_errors()
            # Not deduped — each call is a separate entry
            assert len(errors) == 3
            assert errors[0]["error"] == "HTTP 503: Service Unavailable"
            assert errors[0]["traceback"] == "Traceback:\n  File foo.py\nHTTPError: 503"
            assert errors[2]["error"] == "Connection refused"
            assert "traceback" not in errors[2]  # no traceback passed

    def test_old_errors_pruned(self, tmp_path):
        """Errors older than 7 days should be pruned."""
        status_file = tmp_path / "push_status.json"
        lock_file = tmp_path / "push_status.lock"

        with patch("opentrace.daemon.push_status.PUSH_STATUS_FILE", status_file), \
             patch("opentrace.daemon.push_status._LOCK_FILE", lock_file):
            # Write an old error directly
            old_ts = time.time() - (8 * 24 * 3600)  # 8 days ago
            data = {
                "recent_errors": [
                    {"ts": old_ts, "error": "Old error"}
                ]
            }
            status_file.parent.mkdir(parents=True, exist_ok=True)
            status_file.write_text(json.dumps(data))

            errors = get_recent_errors()
            assert len(errors) == 0  # pruned

    def test_error_ring_buffer_capped(self, tmp_path):
        """Should not exceed _MAX_RECENT_ERRORS entries."""
        status_file = tmp_path / "push_status.json"
        lock_file = tmp_path / "push_status.lock"

        with patch("opentrace.daemon.push_status.PUSH_STATUS_FILE", status_file), \
             patch("opentrace.daemon.push_status._LOCK_FILE", lock_file):
            for i in range(30):
                record_error(f"Error {i}")

            data = json.loads(status_file.read_text())
            assert len(data["recent_errors"]) == 20  # capped at _MAX_RECENT_ERRORS

    def test_traceback_stored_in_file(self, tmp_path):
        """Full traceback text is persisted to push_status.json."""
        status_file = tmp_path / "push_status.json"
        lock_file = tmp_path / "push_status.lock"

        with patch("opentrace.daemon.push_status.PUSH_STATUS_FILE", status_file), \
             patch("opentrace.daemon.push_status._LOCK_FILE", lock_file):
            tb = (
                "Traceback (most recent call last):\n"
                '  File "pusher.py", line 73, in _post_batch\n'
                "    with urllib.request.urlopen(req, timeout=30) as resp:\n"
                "urllib.error.URLError: <urlopen error [Errno 503] Service Unavailable>"
            )
            record_error("HTTP 503", traceback_text=tb)

            data = json.loads(status_file.read_text())
            assert data["recent_errors"][0]["traceback"] == tb
