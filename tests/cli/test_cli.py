# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for the opentrace CLI and progress utility."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from opentrace.cli.traced import (
    _read_pid,
    _write_pid,
    build_parser,
    cmd_doctor,
    cmd_init,
    cmd_logs,
    cmd_start,
    cmd_status,
    cmd_stop,
    main,
)
from opentrace.utils.progress import (
    create_progress,
    read_progress,
    update_progress,
    write_progress,
)


# ---------------------------------------------------------------------------
# Progress utility tests
# ---------------------------------------------------------------------------

class TestProgress:
    """Tests for progress JSON writer/reader."""

    def test_create_progress(self, tmp_path):
        path = tmp_path / "progress.json"
        result = create_progress(
            path,
            agent_name="test-agent",
            worktree="worktrees/test",
            branch="feat/test",
        )

        assert result["agent_name"] == "test-agent"
        assert result["worktree"] == "worktrees/test"
        assert result["branch"] == "feat/test"
        assert result["status"] == "in_progress"
        assert result["completed_at"] is None
        assert result["completed_tasks"] == []
        assert path.exists()

    def test_read_progress(self, tmp_path):
        path = tmp_path / "progress.json"
        create_progress(path, agent_name="a", worktree="w", branch="b")

        data = read_progress(path)
        assert data is not None
        assert data["agent_name"] == "a"

    def test_read_progress_missing_file(self, tmp_path):
        assert read_progress(tmp_path / "nonexistent.json") is None

    def test_update_progress_current_task(self, tmp_path):
        path = tmp_path / "progress.json"
        create_progress(path, agent_name="a", worktree="w", branch="b")

        result = update_progress(path, current_task="Building CLI")
        assert result["current_task"] == "Building CLI"

    def test_update_progress_completed_task(self, tmp_path):
        path = tmp_path / "progress.json"
        create_progress(path, agent_name="a", worktree="w", branch="b")

        update_progress(path, completed_task="Task 1")
        result = update_progress(path, completed_task="Task 2")
        assert result["completed_tasks"] == ["Task 1", "Task 2"]

    def test_update_progress_no_duplicate_tasks(self, tmp_path):
        path = tmp_path / "progress.json"
        create_progress(path, agent_name="a", worktree="w", branch="b")

        update_progress(path, completed_task="Task 1")
        result = update_progress(path, completed_task="Task 1")
        assert result["completed_tasks"] == ["Task 1"]

    def test_update_progress_status_completed(self, tmp_path):
        path = tmp_path / "progress.json"
        create_progress(path, agent_name="a", worktree="w", branch="b")

        result = update_progress(path, status="completed")
        assert result["status"] == "completed"
        assert result["completed_at"] is not None

    def test_update_progress_error(self, tmp_path):
        path = tmp_path / "progress.json"
        create_progress(path, agent_name="a", worktree="w", branch="b")

        result = update_progress(path, error="Something failed")
        assert "Something failed" in result["errors"]

    def test_update_progress_provides_context(self, tmp_path):
        path = tmp_path / "progress.json"
        create_progress(path, agent_name="a", worktree="w", branch="b")

        result = update_progress(
            path, provides_context={"files_created": ["a.py"]}
        )
        assert result["provides_context"]["files_created"] == ["a.py"]

    def test_update_progress_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            update_progress(tmp_path / "nope.json", current_task="x")

    def test_write_progress_atomic(self, tmp_path):
        """Verify atomic write creates valid JSON."""
        path = tmp_path / "progress.json"
        data = {"test": "value", "nested": {"a": 1}}
        write_progress(path, data)

        loaded = json.loads(path.read_text())
        assert loaded == data

    def test_write_progress_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "progress.json"
        write_progress(path, {"ok": True})
        assert path.exists()


# ---------------------------------------------------------------------------
# CLI parser tests
# ---------------------------------------------------------------------------

class TestParser:
    """Tests for argument parser construction."""

    def test_build_parser_returns_parser(self):
        parser = build_parser()
        assert parser.prog == "quickcall"

    def test_parse_start(self):
        parser = build_parser()
        args = parser.parse_args(["start"])
        assert args.command == "start"

    def test_parse_stop(self):
        parser = build_parser()
        args = parser.parse_args(["stop"])
        assert args.command == "stop"

    def test_parse_status(self):
        parser = build_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_parse_logs_default(self):
        parser = build_parser()
        args = parser.parse_args(["logs"])
        assert args.command == "logs"
        assert args.follow is False
        assert args.lines == 50

    def test_parse_logs_follow(self):
        parser = build_parser()
        args = parser.parse_args(["logs", "-f"])
        assert args.follow is True

    def test_parse_logs_lines(self):
        parser = build_parser()
        args = parser.parse_args(["logs", "-n", "100"])
        assert args.lines == 100

    def test_parse_doctor(self):
        parser = build_parser()
        args = parser.parse_args(["doctor"])
        assert args.command == "doctor"

    def test_parse_init(self):
        parser = build_parser()
        args = parser.parse_args(["init"])
        assert args.command == "init"

    def test_parse_up(self):
        parser = build_parser()
        args = parser.parse_args(["up"])
        assert args.command == "up"

    def test_parse_down(self):
        parser = build_parser()
        args = parser.parse_args(["down"])
        assert args.command == "down"

    def test_no_command_returns_1(self):
        assert main([]) == 1


# ---------------------------------------------------------------------------
# PID file tests
# ---------------------------------------------------------------------------

class TestPidHelpers:
    """Tests for PID file read/write."""

    def test_write_and_read_pid(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "test.pid"
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", pid_file)
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", tmp_path)

        _write_pid(os.getpid())
        assert _read_pid() == os.getpid()

    def test_read_pid_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", tmp_path / "nope.pid")
        assert _read_pid() is None

    def test_read_pid_stale(self, tmp_path, monkeypatch):
        """Stale PID (process doesn't exist) should return None."""
        pid_file = tmp_path / "test.pid"
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", pid_file)
        # Use a PID that almost certainly doesn't exist
        pid_file.write_text("99999999")
        assert _read_pid() is None


# ---------------------------------------------------------------------------
# Command tests
# ---------------------------------------------------------------------------

class TestCmdStart:
    """Tests for the start command."""

    def test_start_already_running(self, tmp_path, monkeypatch, capsys):
        pid_file = tmp_path / "test.pid"
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", pid_file)
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", tmp_path)

        # Write current PID to simulate running daemon
        pid_file.write_text(str(os.getpid()))

        with patch("opentrace.cli.traced._is_service_active", return_value=None):
            args = build_parser().parse_args(["start"])
            result = cmd_start(args)

        assert result == 0
        assert "already running" in capsys.readouterr().out

    def test_start_refuses_if_service_active(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", tmp_path / "test.pid")
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", tmp_path)

        with patch("opentrace.cli.traced._is_service_active", return_value="launchd (com.quickcall.daemon)"):
            args = build_parser().parse_args(["start"])
            result = cmd_start(args)

        assert result == 1
        assert "managed by" in capsys.readouterr().out

    def test_start_launches_daemon(self, tmp_path, monkeypatch, capsys):
        pid_file = tmp_path / "test.pid"
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", pid_file)
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", tmp_path)
        monkeypatch.setattr("opentrace.cli.traced.LOG_FILE", tmp_path / "test.log")

        mock_proc = MagicMock()
        mock_proc.pid = 12345

        with patch("opentrace.cli.traced._is_service_active", return_value=None), \
             patch("opentrace.cli.traced._rebootstrap_service", return_value=False), \
             patch("opentrace.cli.traced.subprocess.Popen", return_value=mock_proc):
            args = build_parser().parse_args(["start"])
            result = cmd_start(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "Daemon started (PID 12345)" in out
        assert pid_file.read_text() == "12345"


class TestCmdStop:
    """Tests for the stop command."""

    def test_stop_not_running(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", tmp_path / "nope.pid")
        with patch("opentrace.cli.traced._is_service_active", return_value=None), \
             patch("opentrace.cli.traced._kill_all_opentrace_processes", return_value=0):
            args = build_parser().parse_args(["stop"])
            result = cmd_stop(args)
        assert result == 1
        assert "not running" in capsys.readouterr().out

    def test_stop_sends_sigterm(self, tmp_path, monkeypatch, capsys):
        pid_file = tmp_path / "test.pid"
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", pid_file)

        # Start a subprocess we can actually stop
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        pid_file.write_text(str(proc.pid))

        with patch("opentrace.cli.traced._is_service_active", return_value=None), \
             patch("opentrace.cli.traced._kill_all_opentrace_processes", return_value=0):
            args = build_parser().parse_args(["stop"])
            result = cmd_stop(args)

        assert result == 0
        assert "Daemon stopped" in capsys.readouterr().out
        assert not pid_file.exists()

        # Clean up
        proc.wait(timeout=2)

    def test_stop_service_managed(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", tmp_path / "nope.pid")
        with patch("opentrace.cli.traced._is_service_active", return_value="launchd (com.quickcall.daemon)"), \
             patch("opentrace.cli.traced._stop_service", return_value=True), \
             patch("opentrace.cli.traced._kill_all_opentrace_processes", return_value=0):
            args = build_parser().parse_args(["stop"])
            result = cmd_stop(args)
        assert result == 0
        assert "Service stopped" in capsys.readouterr().out


class TestCmdStatus:
    """Tests for the status command."""

    def test_status_not_running(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", tmp_path / "nope.pid")
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", tmp_path)
        args = build_parser().parse_args(["status"])
        result = cmd_status(args)
        assert result == 0
        assert "not running" in capsys.readouterr().out

    def test_status_running_no_server(self, tmp_path, monkeypatch, capsys):
        pid_file = tmp_path / "test.pid"
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", pid_file)
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", tmp_path)

        pid_file.write_text(str(os.getpid()))

        with patch("opentrace.cli.traced._http_get", return_value=None):
            args = build_parser().parse_args(["status"])
            result = cmd_status(args)

        assert result == 0
        out = capsys.readouterr().out
        assert f"PID {os.getpid()}" in out
        assert "\u2717" in out  # server unreachable marker


    def test_status_shows_queue_and_backoff(self, tmp_path, monkeypatch, capsys):
        """When push_status has non-zero queue/backoff, status displays them."""
        pid_file = tmp_path / "test.pid"
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", pid_file)
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", tmp_path)

        pid_file.write_text(str(os.getpid()))

        # Write a push_status.json with queue metrics
        push_file = tmp_path / "push_status.json"
        push_file.write_text(json.dumps({
            "queue_size": 42,
            "current_backoff": 4.0,
            "last_push_at": 1707558900.0,
            "session_start_at": 1707558800.0,
            "messages_this_session": 100,
        }))

        # Write state.json with at least one source
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "files": {
                "/tmp/a.jsonl": {"source": "claude_code", "last_line_processed": 50}
            }
        }))

        def mock_http_get(path, **kwargs):
            if path == "/health":
                return {"status": "ok"}
            return None

        with patch("opentrace.cli.traced._http_get", side_effect=mock_http_get):
            args = build_parser().parse_args(["status"])
            result = cmd_status(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "42" in out
        assert "queued for retry" in out
        assert "backoff" in out

    def test_status_shows_local_source_table(self, tmp_path, monkeypatch, capsys):
        """Status shows local source table with file/line counts, no cross-org data."""
        pid_file = tmp_path / "test.pid"
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", pid_file)
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", tmp_path)

        pid_file.write_text(str(os.getpid()))

        # Write state.json with two sources
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "files": {
                "/tmp/a.jsonl": {"source": "claude_code", "last_line_processed": 100},
                "/tmp/b.jsonl": {"source": "claude_code", "last_line_processed": 50},
                "/tmp/c.jsonl": {"source": "cursor", "last_line_processed": 200},
            }
        }))

        # Write push_status.json with per-source timestamps
        push_file = tmp_path / "push_status.json"
        push_file.write_text(json.dumps({
            "last_push_at": 1707558900.0,
            "by_source": {
                "claude_code": {"last_push_at": 1707558900.0, "messages_pushed": 140},
                "cursor": {"last_push_at": 1707558800.0, "messages_pushed": 180},
            }
        }))

        def mock_http_get(path, **kwargs):
            if path == "/health":
                return {"status": "ok"}
            return None

        with patch("opentrace.cli.traced._http_get", side_effect=mock_http_get):
            args = build_parser().parse_args(["status"])
            result = cmd_status(args)

        assert result == 0
        out = capsys.readouterr().out

        # Source names appear
        assert "Claude Code" in out
        assert "Cursor" in out

        # File and line counts appear
        assert "150" in out   # claude_code: 100 + 50 lines
        assert "200" in out   # cursor: 200 lines
        assert "2" in out     # claude_code: 2 files

        # Summary line
        assert "files" in out
        assert "lines processed" in out

        # No cross-org server stats leaked
        assert "sessions" not in out.lower() or "session" not in out.split("lines")[0].lower()
        assert "messages" not in out.lower() or "messages/min" in out.lower() or "messages queued" in out.lower()


class TestCmdLogs:
    """Tests for the logs command."""

    def test_logs_missing_file(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("opentrace.cli.traced.LOG_FILE", tmp_path / "nope.log")
        args = build_parser().parse_args(["logs"])
        result = cmd_logs(args)
        assert result == 1
        assert "not found" in capsys.readouterr().out

    def test_logs_reads_last_n(self, tmp_path, monkeypatch, capsys):
        log_file = tmp_path / "test.log"
        lines = [f"Line {i}" for i in range(100)]
        log_file.write_text("\n".join(lines))

        monkeypatch.setattr("opentrace.cli.traced.LOG_FILE", log_file)

        args = build_parser().parse_args(["logs", "-n", "5"])
        result = cmd_logs(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "Line 95" in out
        assert "Line 99" in out
        assert "Line 50" not in out



# ---------------------------------------------------------------------------
# Main entry point tests
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Doctor command tests
# ---------------------------------------------------------------------------

class TestCmdDoctor:
    """Tests for quickcall doctor."""

    def test_doctor_all_healthy(self, tmp_path, monkeypatch, capsys):
        config_dir = tmp_path / "qc"
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)

        with patch("opentrace.cli.traced._http_get", return_value={"status": "ok"}), \
             patch("opentrace.cli.traced.shutil.which", return_value="/usr/bin/docker"), \
             patch("opentrace.cli.traced._find_compose_file", return_value=tmp_path / "docker-compose.yml"), \
             patch("opentrace.cli.traced._find_session_dirs", return_value=[Path("/home/user/.claude")]):
            args = build_parser().parse_args(["doctor"])
            result = cmd_doctor(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "Docker" in out
        assert "docker-compose.yml" in out
        assert "Server" in out
        assert "Session dirs" in out

    def test_doctor_no_docker_shows_warning(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", tmp_path)

        with patch("opentrace.cli.traced.shutil.which", return_value=None), \
             patch("opentrace.cli.traced._http_get", return_value=None):
            args = build_parser().parse_args(["doctor"])
            result = cmd_doctor(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "Docker" in out and "not found" in out

    def test_doctor_server_unhealthy_shows_x(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", tmp_path)

        with patch("opentrace.cli.traced.shutil.which", return_value="/usr/bin/docker"), \
             patch("opentrace.cli.traced._find_compose_file", return_value=tmp_path / "docker-compose.yml"), \
             patch("opentrace.cli.traced._http_get", return_value=None), \
             patch("opentrace.cli.traced._find_session_dirs", return_value=[]):
            args = build_parser().parse_args(["doctor"])
            result = cmd_doctor(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "unreachable" in out


# ---------------------------------------------------------------------------
# Init command tests
# ---------------------------------------------------------------------------

class TestCmdInit:
    """Tests for quickcall init."""

    def test_init_creates_config_dir(self, tmp_path, monkeypatch, capsys):
        config_dir = tmp_path / "qc"
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", config_dir)

        with patch("opentrace.cli.traced._test_dsn", return_value=True):
            args = build_parser().parse_args(["init"])
            result = cmd_init(args)

        assert result == 0
        assert config_dir.exists()
        assert (config_dir / "config.json").exists()

    def test_init_writes_config_json(self, tmp_path, monkeypatch, capsys):
        config_dir = tmp_path / "qc"
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", config_dir)

        with patch("opentrace.cli.traced._test_dsn", return_value=True):
            args = build_parser().parse_args(["init"])
            cmd_init(args)

        config = json.loads((config_dir / "config.json").read_text())
        assert "dsn" in config
        assert "api_key" in config

    def test_init_bad_dsn_warns(self, tmp_path, monkeypatch, capsys):
        config_dir = tmp_path / "qc"
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", config_dir)

        with patch("opentrace.cli.traced._test_dsn", return_value=False):
            args = build_parser().parse_args(["init"])
            result = cmd_init(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "Could not connect" in out

    def test_init_skips_if_config_exists(self, tmp_path, monkeypatch, capsys):
        config_dir = tmp_path / "qc"
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", config_dir)
        config_dir.mkdir()
        (config_dir / "config.json").write_text('{"dsn": "existing"}')

        args = build_parser().parse_args(["init"])
        result = cmd_init(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "already exists" in out


# ---------------------------------------------------------------------------
# Main entry point tests
# ---------------------------------------------------------------------------

class TestMain:
    """Tests for the main() entry point."""

    def test_main_start(self, tmp_path, monkeypatch):
        monkeypatch.setattr("opentrace.cli.traced.PID_FILE", tmp_path / "nope.pid")
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", tmp_path)
        monkeypatch.setattr("opentrace.cli.traced.LOG_FILE", tmp_path / "test.log")

        mock_proc = MagicMock()
        mock_proc.pid = 42

        with patch("opentrace.cli.traced._is_service_active", return_value=None), \
             patch("opentrace.cli.traced._rebootstrap_service", return_value=False), \
             patch("opentrace.cli.traced.subprocess.Popen", return_value=mock_proc):
            assert main(["start"]) == 0

    def test_main_doctor(self, tmp_path, monkeypatch):
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", tmp_path)
        with patch("opentrace.cli.traced._http_get", return_value={"status": "ok"}), \
             patch("opentrace.cli.traced.shutil.which", return_value="/usr/bin/docker"), \
             patch("opentrace.cli.traced._find_compose_file", return_value=tmp_path / "docker-compose.yml"), \
             patch("opentrace.cli.traced._find_session_dirs", return_value=[Path("/home/user/.claude")]):
            assert main(["doctor"]) == 0

    def test_main_init(self, tmp_path, monkeypatch):
        monkeypatch.setattr("opentrace.cli.traced.QUICKCALL_OPENTRACE_DIR", tmp_path)
        with patch("opentrace.cli.traced._test_dsn", return_value=True):
            assert main(["init"]) == 0

    def test_main_unknown_command(self):
        # argparse exits on unrecognized commands
        with pytest.raises(SystemExit):
            main(["unknown"])
