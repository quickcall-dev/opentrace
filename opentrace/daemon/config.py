# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Daemon configuration."""

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = 19777
DEFAULT_INGEST_URL = "http://localhost:19777/ingest"


def _default_base_dir() -> Path:
    return Path(os.environ.get("QUICKCALL_OPENTRACE_CONFIG_DIR", str(Path.home() / ".quickcall-opentrace")))


def _default_ingest_url() -> str:
    return os.environ.get("QUICKCALL_OPENTRACE_INGEST_URL", DEFAULT_INGEST_URL)


@dataclass
class DaemonConfig:
    """Configuration for the QuickCall OpenTrace daemon."""

    # Polling
    poll_interval: float = 10.0  # seconds
    glob_refresh_interval: float = 30.0  # seconds between full re-globs
    rc_enabled: bool = False

    # Paths
    base_dir: Path = field(default_factory=_default_base_dir)

    # Ingest server (override with QUICKCALL_OPENTRACE_INGEST_URL env var)
    ingest_url: str = field(default_factory=_default_ingest_url)

    # File limits
    max_file_size: int = 100 * 1024 * 1024  # 100MB
    max_retries_per_file: int = 3
    # Max files to process per cycle (0 = unlimited).
    # When set, only the N most recently modified files are processed.
    # Useful for dev testing to avoid pushing all historical sessions.
    # Set via QUICKCALL_OPENTRACE_MAX_FILES env var or config.json "max_files".
    max_files: int = 0

    # Retry / pusher
    retry_backoff_base: float = 1.0  # seconds
    retry_backoff_max: float = 60.0  # seconds
    retry_queue_max: int = 10_000  # max messages in retry queue
    retry_timeout: float = 300.0  # 5 min persistent failure threshold
    retry_cooldown: float = 300.0  # seconds before backoff decays

    # Batch size for push
    batch_size: int = 500

    # Internal: log per-phase wall/cpu/io timing for each poll cycle.
    # Enable with QUICKCALL_OPENTRACE_PROFILE_POLLS=1 env var.
    profile_polls: bool = False

    # Organization (set via QUICKCALL_OPENTRACE_ORG env var or config.json)
    org: str | None = None

    # API key for server auth (set via QUICKCALL_OPENTRACE_API_KEY env var or config.json)
    api_key: str | None = None

    # Device ID (persistent UUID generated at install, read from config.json)
    device_id: str | None = None

    # Scoped installation: only collect sessions whose cwd is under these paths
    scoped_mode: bool = False
    scoped_paths: list[str] = field(default_factory=list)

    # Source glob patterns (relative to home)
    claude_code_glob: str = ".claude/projects/**/*.jsonl"
    codex_cli_glob: str = ".codex/sessions/*/*/*/rollout-*.jsonl"
    gemini_cli_glob: str = ".gemini/tmp/*/chats/session-*.json"
    cursor_glob: str = ".cursor/projects/*/agent-transcripts/*.txt"
    cursor_vscdb_glob: str = "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
    pi_glob: str = ".pi/agent/sessions/**/*.jsonl"

    def __post_init__(self) -> None:
        """Resolve settings from env vars and config.json."""
        config_data: dict | None = None
        config_path = self.base_dir / "config.json"
        if config_path.exists():
            try:
                config_data = json.loads(config_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        # Resolve org: config.json > env > None.
        if self.org is None:
            if config_data:
                self.org = config_data.get("org")
            if self.org is None:
                self.org = os.environ.get("QUICKCALL_OPENTRACE_ORG")

        # Resolve api_key: env > config.json > None
        if self.api_key is None:
            env_key = os.environ.get("QUICKCALL_OPENTRACE_API_KEY")
            if env_key:
                self.api_key = env_key
            elif config_data:
                self.api_key = config_data.get("api_key")

        # Resolve device_id: .device_id file > config.json > auto-generate
        if self.device_id is None:
            device_id_file = self.base_dir / ".device_id"
            if device_id_file.exists():
                try:
                    self.device_id = device_id_file.read_text().strip()
                except OSError:
                    pass
            if self.device_id is None and config_data:
                self.device_id = config_data.get("device_id")
            if self.device_id is None:
                self.device_id = str(uuid.uuid4())
                try:
                    self.base_dir.mkdir(parents=True, exist_ok=True)
                    device_id_file.write_text(self.device_id)
                except OSError:
                    pass

        # Resolve scoped_mode and scoped_paths from config.json
        if not self.scoped_mode and config_data:
            self.scoped_mode = config_data.get("scoped_mode", False)
        if not self.scoped_paths and config_data:
            self.scoped_paths = config_data.get("scoped_paths", [])

        # Resolve ingest_url: explicit arg > env > config.json > default
        if self.ingest_url == DEFAULT_INGEST_URL:
            env_url = os.environ.get("QUICKCALL_OPENTRACE_INGEST_URL")
            if env_url:
                self.ingest_url = env_url
            elif config_data and config_data.get("ingest_url"):
                self.ingest_url = config_data["ingest_url"]

        # Resolve rc_enabled from env var
        if not self.rc_enabled:
            self.rc_enabled = os.environ.get("QUICKCALL_OPENTRACE_RC", "") == "1"

        # Resolve max_files: env > config.json > 0 (unlimited)
        if self.max_files == 0:
            env_max = os.environ.get("QUICKCALL_OPENTRACE_MAX_FILES", "")
            if env_max.isdigit() and int(env_max) > 0:
                self.max_files = int(env_max)
            elif config_data:
                self.max_files = config_data.get("max_files", 0)

        # Internal profiling flag: env var > config.json
        if not self.profile_polls:
            env_profile = os.environ.get("QUICKCALL_OPENTRACE_PROFILE_POLLS", "")
            if env_profile == "1":
                self.profile_polls = True
            elif config_data:
                self.profile_polls = config_data.get("profile_polls", False)

    def is_path_in_scope(self, cwd: str | None) -> bool:
        """Check if a cwd falls under any scoped path.

        Returns True if scoped_mode is off, or if cwd is under a scoped path.
        Returns False if scoped_mode is on and cwd is None or not under any scoped path.
        """
        if not self.scoped_mode:
            return True
        if not cwd:
            return False
        cwd_path = Path(cwd).resolve()
        for sp in self.scoped_paths:
            scope_path = Path(sp).resolve()
            try:
                cwd_path.relative_to(scope_path)
                return True
            except ValueError:
                continue
        return False

    @property
    def state_file(self) -> Path:
        return self.base_dir / "state.json"

    @property
    def pid_file(self) -> Path:
        return self.base_dir / "quickcall.pid"
