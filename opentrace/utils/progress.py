# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Progress JSON writer/reader for agent coordination.

Writes and reads progress files used for inter-agent communication
during parallel worktree builds. Each agent writes its status to a
JSON file that other agents can check for dependencies and context.
"""


import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_progress(
    path: str | Path,
    *,
    agent_name: str,
    worktree: str,
    branch: str,
) -> dict[str, Any]:
    """Create a new progress file with initial state.

    Returns the created progress dict.
    """
    progress: dict[str, Any] = {
        "agent_name": agent_name,
        "worktree": worktree,
        "branch": branch,
        "status": "in_progress",
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
        "completed_at": None,
        "current_task": "",
        "completed_tasks": [],
        "blocked_by": [],
        "provides_context": {},
        "issues": [],
        "errors": [],
    }
    write_progress(path, progress)
    return progress


def write_progress(path: str | Path, data: dict[str, Any]) -> None:
    """Atomically write progress JSON to disk.

    Uses a temporary file + rename to prevent partial reads.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=".progress_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_progress(path: str | Path) -> dict[str, Any] | None:
    """Read a progress JSON file. Returns None if file doesn't exist."""
    path = Path(path)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def update_progress(
    path: str | Path,
    *,
    current_task: str | None = None,
    status: str | None = None,
    completed_task: str | None = None,
    provides_context: dict[str, Any] | None = None,
    error: str | None = None,
    blocked_by: list[str] | None = None,
) -> dict[str, Any]:
    """Update an existing progress file.

    Reads the current state, applies updates, and writes back atomically.
    Returns the updated progress dict.
    """
    path = Path(path)
    data = read_progress(path)
    if data is None:
        raise FileNotFoundError(f"Progress file not found: {path}")

    data["updated_at"] = _now_iso()

    if current_task is not None:
        data["current_task"] = current_task

    if status is not None:
        data["status"] = status
        if status == "completed":
            data["completed_at"] = _now_iso()

    if completed_task is not None:
        if completed_task not in data["completed_tasks"]:
            data["completed_tasks"].append(completed_task)

    if provides_context is not None:
        data["provides_context"].update(provides_context)

    if error is not None:
        data["errors"].append(error)

    if blocked_by is not None:
        data["blocked_by"] = blocked_by

    write_progress(path, data)
    return data
