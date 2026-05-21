# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for push_status tracking."""


import time

import pytest

from opentrace.daemon.push_status import (
    init_session,
    record_push,
    record_push_metrics,
    read_push_status,
)


@pytest.fixture(autouse=True)
def _clean_status(tmp_path, monkeypatch):
    """Redirect push_status to a temp file for every test."""
    tmp_file = tmp_path / "push_status.json"
    monkeypatch.setattr("opentrace.daemon.push_status.PUSH_STATUS_FILE", tmp_file)
    yield


class TestRecordPush:
    def test_sets_first_push_at_on_first_call(self):
        record_push("claude_code", 10)
        data = read_push_status()
        assert "first_push_at" in data
        assert data["first_push_at"] > 0

    def test_first_push_at_not_overwritten(self):
        record_push("claude_code", 10)
        first = read_push_status()["first_push_at"]

        time.sleep(0.01)
        record_push("claude_code", 5)
        assert read_push_status()["first_push_at"] == first

    def test_increments_total_messages_pushed(self):
        record_push("claude_code", 10)
        assert read_push_status()["total_messages_pushed"] == 10

        record_push("claude_code", 7)
        assert read_push_status()["total_messages_pushed"] == 17

    def test_increments_messages_this_session(self):
        record_push("claude_code", 3)
        assert read_push_status()["messages_this_session"] == 3

        record_push("gemini_cli", 5)
        assert read_push_status()["messages_this_session"] == 8

    def test_updates_last_push_at(self):
        record_push("claude_code", 1)
        t1 = read_push_status()["last_push_at"]

        time.sleep(0.01)
        record_push("claude_code", 1)
        t2 = read_push_status()["last_push_at"]
        assert t2 > t1

    def test_tracks_by_source(self):
        record_push("claude_code", 10)
        record_push("gemini_cli", 5)
        data = read_push_status()
        assert data["by_source"]["claude_code"]["messages_pushed"] == 10
        assert data["by_source"]["gemini_cli"]["messages_pushed"] == 5


class TestInitSession:
    def test_sets_session_start_and_resets_counter(self):
        # Simulate some pushes from a previous session
        record_push("claude_code", 50)
        assert read_push_status()["messages_this_session"] == 50

        init_session()
        data = read_push_status()
        assert data["messages_this_session"] == 0
        assert data["session_start_at"] > 0

    def test_preserves_total_messages_pushed(self):
        record_push("claude_code", 50)
        init_session()
        data = read_push_status()
        assert data["total_messages_pushed"] == 50

    def test_preserves_first_push_at(self):
        record_push("claude_code", 10)
        first = read_push_status()["first_push_at"]
        init_session()
        assert read_push_status()["first_push_at"] == first


class TestRecordPushMetrics:
    def test_records_queue_size_and_backoff(self):
        record_push_metrics(42, 4.0)
        data = read_push_status()
        assert data["queue_size"] == 42
        assert data["current_backoff"] == 4.0

    def test_updates_existing_values(self):
        record_push_metrics(10, 2.0)
        record_push_metrics(0, 0.0)
        data = read_push_status()
        assert data["queue_size"] == 0
        assert data["current_backoff"] == 0.0

    def test_preserves_other_fields(self):
        record_push("claude_code", 5)
        record_push_metrics(3, 1.5)
        data = read_push_status()
        assert data["total_messages_pushed"] == 5
        assert data["queue_size"] == 3
