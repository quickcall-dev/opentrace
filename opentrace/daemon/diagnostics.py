# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Lightweight diagnostics for source file discovery.

All functions here are best-effort and must never raise.
"""


import glob
import os
import sqlite3
from pathlib import Path

from opentrace.daemon.config import DaemonConfig


def build_source_diagnostics(config: DaemonConfig) -> dict:
    """Build diagnostics dict for sources that use fixed paths (not globs).

    Returns a JSON-serializable diagnostics dict.
    Never raises — returns {} on any error.
    """
    try:
        return {
            "cursor_vscdb": _diagnose_cursor_vscdb(config),
        }
    except Exception:
        return {}


def _diagnose_cursor_vscdb(config: DaemonConfig) -> dict:
    """Walk the cursor vscdb path and report where access breaks."""
    home = str(Path.home())
    expected = os.path.join(home, config.cursor_vscdb_glob)

    result: dict = {"home": home, "expected_path": expected}

    # Walk each directory segment
    parts = Path(expected).parts
    path_walk = []
    for i in range(2, len(parts)):  # skip "/" and home dir itself
        segment = str(Path(*parts[:i + 1]))
        entry: dict = {"path": segment}
        try:
            entry["exists"] = os.path.exists(segment)
            if entry["exists"]:
                entry["readable"] = os.access(segment, os.R_OK)
            else:
                entry["readable"] = False
        except Exception as e:
            entry["exists"] = False
            entry["readable"] = False
            entry["error"] = f"{type(e).__name__}: {e}"
        path_walk.append(entry)
    result["path_walk"] = path_walk

    # File-level checks
    try:
        stat = os.stat(expected)
        result["file_exists"] = True
        result["file_size"] = stat.st_size
        result["file_readable"] = os.access(expected, os.R_OK)
    except FileNotFoundError:
        result["file_exists"] = False
        result["file_readable"] = False
        result["file_size"] = None
    except Exception as e:
        result["file_exists"] = False
        result["file_readable"] = False
        result["file_size"] = None
        result["file_error"] = f"{type(e).__name__}: {e}"

    # SQLite connectivity check (only if file exists and readable)
    if result.get("file_readable"):
        try:
            conn = sqlite3.connect(f"file:{expected}?mode=ro", uri=True, timeout=2)
            conn.execute("SELECT 1 FROM cursorDiskKV LIMIT 1")
            conn.close()
            result["sqlite_ok"] = True
        except Exception as e:
            result["sqlite_ok"] = False
            result["sqlite_error"] = f"{type(e).__name__}: {e}"
    else:
        result["sqlite_ok"] = False

    # What the glob actually found
    full_pattern = os.path.join(home, config.cursor_vscdb_glob)
    try:
        result["glob_result_count"] = len(glob.glob(full_pattern))
    except Exception:
        result["glob_result_count"] = 0

    return result
