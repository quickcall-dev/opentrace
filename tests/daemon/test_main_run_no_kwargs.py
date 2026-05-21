# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale


from unittest.mock import MagicMock

import pytest

from opentrace.daemon.main import Daemon, run
from tests.helpers import make_message


@pytest.fixture
def daemon_runtime_patch(monkeypatch):
    monkeypatch.setattr("opentrace.daemon.main.Daemon._setup_signals", lambda self: None)
    monkeypatch.setattr("opentrace.daemon.main.Daemon._write_pid", lambda self: None)
    monkeypatch.setattr("opentrace.daemon.main.Daemon._reconcile", lambda self: None)
    monkeypatch.setattr("opentrace.daemon.main.Daemon._truncate_err_log", lambda self: None)
    monkeypatch.setattr("opentrace.daemon.main.Daemon._cleanup", lambda self: None)
    monkeypatch.setattr("opentrace.daemon.main.resolve_global_identity", lambda: ("candidate@example.com", "Candidate"))
    monkeypatch.setattr("opentrace.daemon.main.socket.gethostname", lambda: "test-host")



def _single_cycle_poll(self):
    msgs = [make_message(id="m1", session_id="s1")]
    if self._event_filter is not None:
        msgs = [m for m in msgs if self._event_filter(m)]
    if msgs:
        self.pusher.push(msgs)
    self._shutdown = True



def test_daemon_constructor_kwargs_remain_optional():
    Daemon()
    Daemon(config=None)
    Daemon(event_filter=lambda _m: True, on_startup=lambda _cfg: None)



def test_run_no_kwargs_still_pushes(monkeypatch, daemon_runtime_patch):
    pushed = {"count": 0}

    def _push(msgs):
        pushed["count"] += len(msgs)
        return True

    monkeypatch.setattr("opentrace.daemon.main.Daemon._poll_cycle", _single_cycle_poll)
    monkeypatch.setattr("opentrace.daemon.main.Pusher.push", lambda self, msgs: _push(msgs))
    monkeypatch.setenv("QUICKCALL_OPENTRACE_INGEST_URL", "http://127.0.0.1:9/ingest")

    assert run() == 0
    assert pushed["count"] == 1



def test_run_event_filter_false_pushes_nothing(monkeypatch, daemon_runtime_patch):
    pushed = {"count": 0}

    def _push(msgs):
        pushed["count"] += len(msgs)
        return True

    monkeypatch.setattr("opentrace.daemon.main.Daemon._poll_cycle", _single_cycle_poll)
    monkeypatch.setattr("opentrace.daemon.main.Pusher.push", lambda self, msgs: _push(msgs))
    monkeypatch.setenv("QUICKCALL_OPENTRACE_INGEST_URL", "http://127.0.0.1:9/ingest")

    assert run(event_filter=lambda _m: False) == 0
    assert pushed["count"] == 0



def test_run_on_startup_called_once(monkeypatch, daemon_runtime_patch):
    started = MagicMock()

    monkeypatch.setattr("opentrace.daemon.main.Daemon._poll_cycle", _single_cycle_poll)
    monkeypatch.setattr("opentrace.daemon.main.Pusher.push", lambda self, msgs: True)
    monkeypatch.setenv("QUICKCALL_OPENTRACE_INGEST_URL", "http://127.0.0.1:9/ingest")

    assert run(on_startup=started) == 0
    started.assert_called_once()
