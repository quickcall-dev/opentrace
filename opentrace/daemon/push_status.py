# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Lightweight push status tracking — stdlib only.

Uses fcntl file locking to prevent race conditions when the old daemon
process (being killed) and the new daemon overlap briefly.
"""


import fcntl
import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PUSH_STATUS_FILE = Path(
    os.environ.get(
        "QUICKCALL_OPENTRACE_PUSH_STATUS_FILE",
        str(Path(os.environ.get("QUICKCALL_OPENTRACE_CONFIG_DIR", str(Path.home() / ".quickcall-opentrace"))) / "push_status.json"),
    )
)
_LOCK_FILE = PUSH_STATUS_FILE.with_suffix(".lock")


@contextmanager
def _locked():
    """Acquire an exclusive file lock for read-modify-write operations."""
    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_file() -> dict:
    if not PUSH_STATUS_FILE.exists():
        return {}
    try:
        return json.loads(PUSH_STATUS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_file(data: dict) -> None:
    PUSH_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=PUSH_STATUS_FILE.parent, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, PUSH_STATUS_FILE)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def init_session() -> None:
    """Mark the start of a new daemon session. Call once on daemon startup."""
    with _locked():
        data = _read_file()
        data["session_start_at"] = time.time()
        data["messages_this_session"] = 0
        _write_file(data)


def record_push(source: str, message_count: int) -> None:
    """Record a successful push for a source."""
    now = time.time()
    with _locked():
        data = _read_file()
        data["last_push_at"] = now

        # First-push timestamp (set once, never overwritten)
        if "first_push_at" not in data:
            data["first_push_at"] = now

        # Running totals
        data["total_messages_pushed"] = data.get("total_messages_pushed", 0) + message_count
        data["messages_this_session"] = data.get("messages_this_session", 0) + message_count

        by_source = data.setdefault("by_source", {})
        src = by_source.setdefault(source, {"last_push_at": 0, "messages_pushed": 0})
        src["last_push_at"] = now
        src["messages_pushed"] += message_count

        _write_file(data)


def record_update_check(
    daemon_version: str,
    available_update: str | None = None,
) -> None:
    """Record the result of an auto-update check."""
    with _locked():
        data = _read_file()
        data["daemon_version"] = daemon_version
        data["last_update_check"] = time.time()
        if available_update:
            data["available_update"] = available_update
        else:
            data.pop("available_update", None)
        _write_file(data)


def record_push_metrics(queue_size: int, backoff: float) -> None:
    """Record current pusher queue and backoff state."""
    with _locked():
        data = _read_file()
        data["queue_size"] = queue_size
        data["current_backoff"] = round(backoff, 1)
        _write_file(data)


_MAX_RECENT_ERRORS = 20
_ERROR_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def record_error(error_message: str, traceback_text: str | None = None) -> None:
    """Record a push error with optional full traceback."""
    now = time.time()
    with _locked():
        data = _read_file()
        errors: list[dict] = data.get("recent_errors", [])

        entry: dict = {"ts": now, "error": error_message}
        if traceback_text:
            entry["traceback"] = traceback_text

        errors.append(entry)

        # Prune old entries
        cutoff = now - _ERROR_TTL_SECONDS
        errors = [e for e in errors if e.get("ts", 0) > cutoff]

        # Keep only last N
        if len(errors) > _MAX_RECENT_ERRORS:
            errors = errors[-_MAX_RECENT_ERRORS:]

        data["recent_errors"] = errors
        _write_file(data)


def get_recent_errors_summary() -> list[dict]:
    """Return condensed recent errors without tracebacks.

    Deduplicates by error message with counts for a compact payload.
    """
    now = time.time()
    cutoff = now - _ERROR_TTL_SECONDS
    data = _read_file()
    errors: list[dict] = data.get("recent_errors", [])

    # Deduplicate by message for a compact status payload.
    by_msg: dict[str, dict] = {}
    for e in errors:
        if e.get("ts", 0) <= cutoff:
            continue
        msg = e.get("error", "unknown")
        if msg in by_msg:
            by_msg[msg]["count"] += 1
            by_msg[msg]["ts"] = max(by_msg[msg]["ts"], e["ts"])
        else:
            by_msg[msg] = {"ts": e["ts"], "error": msg, "count": 1}

    result = []
    for entry in by_msg.values():
        ts_iso = datetime.fromtimestamp(entry["ts"], tz=timezone.utc).isoformat()
        result.append({"ts": ts_iso, "error": entry["error"], "count": entry["count"]})
    return result


def get_recent_errors() -> list[dict]:
    """Return recent errors with full tracebacks for local display."""
    now = time.time()
    cutoff = now - _ERROR_TTL_SECONDS
    data = _read_file()
    errors: list[dict] = data.get("recent_errors", [])
    return [e for e in errors if e.get("ts", 0) > cutoff]


def read_push_status() -> dict:
    """Read the push status file."""
    return _read_file()
