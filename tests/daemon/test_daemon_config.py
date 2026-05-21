# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for DaemonConfig defaults and derived properties (M1)."""


from pathlib import Path


from opentrace.daemon.config import DaemonConfig


class TestDaemonConfigDefaults:
    def test_default_poll_interval(self):
        c = DaemonConfig()
        assert c.poll_interval == 10.0

    def test_default_base_dir(self):
        c = DaemonConfig()
        assert c.base_dir == Path.home() / ".quickcall-opentrace"

    def test_default_ingest_url(self):
        c = DaemonConfig()
        assert c.ingest_url == "http://localhost:19777/ingest"

    def test_default_max_file_size(self):
        c = DaemonConfig()
        assert c.max_file_size == 100 * 1024 * 1024

    def test_default_batch_size(self):
        c = DaemonConfig()
        assert c.batch_size == 500

    def test_default_retry_settings(self):
        c = DaemonConfig()
        assert c.retry_backoff_base == 1.0
        assert c.retry_backoff_max == 60.0
        assert c.retry_queue_max == 10_000
        assert c.retry_timeout == 300.0
        assert c.max_retries_per_file == 3


class TestDaemonConfigDerived:
    def test_state_file_derived(self):
        c = DaemonConfig(base_dir=Path("/tmp/test"))
        assert c.state_file == Path("/tmp/test/state.json")

    def test_pid_file_derived(self):
        c = DaemonConfig(base_dir=Path("/tmp/test"))
        assert c.pid_file == Path("/tmp/test/quickcall.pid")


class TestDaemonConfigGlobs:
    def test_claude_code_glob(self):
        c = DaemonConfig()
        assert "claude" in c.claude_code_glob
        assert c.claude_code_glob.endswith(".jsonl")

    def test_codex_cli_glob(self):
        c = DaemonConfig()
        assert "codex" in c.codex_cli_glob
        assert c.codex_cli_glob.endswith(".jsonl")

    def test_gemini_cli_glob(self):
        c = DaemonConfig()
        assert "gemini" in c.gemini_cli_glob
        assert c.gemini_cli_glob.endswith(".json")

    def test_cursor_glob(self):
        c = DaemonConfig()
        assert "cursor" in c.cursor_glob
        assert c.cursor_glob.endswith(".txt")


class TestDaemonConfigOverrides:
    def test_override_base_dir(self, tmp_path: Path):
        c = DaemonConfig(base_dir=tmp_path)
        assert c.base_dir == tmp_path
        assert c.state_file == tmp_path / "state.json"

    def test_override_ingest_url(self):
        c = DaemonConfig(ingest_url="http://custom:8080/ingest")
        assert c.ingest_url == "http://custom:8080/ingest"

    def test_override_poll_interval(self):
        c = DaemonConfig(poll_interval=10.0)
        assert c.poll_interval == 10.0
