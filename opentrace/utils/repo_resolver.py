# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale


import json
import os
import re
import subprocess
import tempfile
import time as _time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RepoInfo:
    """Git repository information resolved from a working directory."""

    cwd: str
    repo_url: str | None = None
    repo_name: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    user_email: str | None = None
    user_name: str | None = None


# TTL cache for resolve_repo results: cwd -> (timestamp, RepoInfo)
_repo_cache: dict[str, tuple[float, RepoInfo]] = {}
_REPO_CACHE_TTL = 300.0  # 5 minutes

_QC_DIR = Path(os.environ.get("QUICKCALL_OPENTRACE_CONFIG_DIR", str(Path.home() / ".quickcall-opentrace")))
_REPO_CACHE_FILE = _QC_DIR / "repo-cache.json"


def _update_disk_cache(cwd: str, repo_name: str) -> None:
    """Atomically update the QuickCall OpenTrace repo cache with cwd -> repo_name."""
    try:
        _QC_DIR.mkdir(parents=True, exist_ok=True)
        existing: dict[str, str] = {}
        if _REPO_CACHE_FILE.exists():
            try:
                existing = json.loads(_REPO_CACHE_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        if existing.get(cwd) == repo_name:
            return
        existing[cwd] = repo_name
        fd, tmp = tempfile.mkstemp(dir=str(_QC_DIR), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(existing, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, str(_REPO_CACHE_FILE))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception:
        pass  # never crash the daemon over cache writes


def load_repo_cache() -> dict[str, str]:
    """Read the QuickCall OpenTrace repo cache. Returns cwd -> repo_name dict."""
    try:
        if _REPO_CACHE_FILE.exists():
            return json.loads(_REPO_CACHE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def resolve_repo(cwd: str) -> RepoInfo:
    """Run git commands against cwd to get repo + identity info.

    Returns RepoInfo with whatever fields could be resolved.
    Non-git directories get back RepoInfo(cwd=cwd) with everything else None.
    Results are cached for 5 minutes per cwd.
    If repo_name is resolved, also updates the QuickCall OpenTrace repo cache.
    """
    now = _time.monotonic()
    cached = _repo_cache.get(cwd)
    if cached is not None:
        cache_time, info = cached
        if now - cache_time < _REPO_CACHE_TTL:
            return info

    info = RepoInfo(cwd=cwd)

    repo_url = _git_cmd(cwd, ["remote", "get-url", "origin"])
    if repo_url is not None:
        info.repo_url = repo_url
        info.repo_name = _extract_repo_name(repo_url)

    info.git_branch = _git_cmd(cwd, ["rev-parse", "--abbrev-ref", "HEAD"])
    info.git_commit = _git_cmd(cwd, ["rev-parse", "HEAD"])
    info.user_email = _git_cmd(cwd, ["config", "user.email"])
    info.user_name = _git_cmd(cwd, ["config", "user.name"])

    _repo_cache[cwd] = (now, info)
    if info.repo_name:
        _update_disk_cache(cwd, info.repo_name)
    return info


def clear_repo_cache() -> None:
    """Clear the resolve_repo TTL cache (useful for testing)."""
    _repo_cache.clear()


def resolve_global_identity() -> tuple[str | None, str | None]:
    """Fallback identity from global git config.

    Returns (email, name) from:
    - git config --global user.email
    - git config --global user.name
    """
    try:
        email_result = subprocess.run(
            ["git", "config", "--global", "user.email"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        email = email_result.stdout.strip() if email_result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        email = None

    try:
        name_result = subprocess.run(
            ["git", "config", "--global", "user.name"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        name = name_result.stdout.strip() if name_result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        name = None

    return email, name


def decode_cursor_slug(slug: str) -> str | None:
    """Decode Cursor project slug to filesystem path.

    Cursor replaces '/' with '-' in project slugs, but directory names can
    also contain dashes, making decoding ambiguous.

    Examples:
        'home-test-repo'    -> '/home/test/repo'
        'Users-example-work-project'             -> '/Users/example/work/project'

    Strategy: try all possible dash-to-slash splits, validate with os.path.isdir(),
    prefer the longest (deepest) valid path.
    """
    if not slug:
        return None

    parts = slug.split("-")
    if not parts:
        return None

    # Try to find a valid path by recursively building from left to right.
    # Limit recursion depth to avoid exponential blowup on pathological slugs.
    max_depth = 20
    best: str | None = None

    def _search(idx: int, current: str, depth: int) -> None:
        nonlocal best
        if depth > max_depth:
            return
        if idx == len(parts):
            if os.path.isdir(current):
                if best is None or len(current) > len(best):
                    best = current
            return

        # Option 1: start a new path segment (dash becomes /)
        new_seg = current + "/" + parts[idx]
        if os.path.isdir(new_seg) or _has_prefix(new_seg):
            _search(idx + 1, new_seg, depth + 1)

        # Option 2: append to current segment with dash (keep dash literal)
        if idx > 0:  # can't append to root
            last_slash = current.rfind("/")
            if last_slash >= 0:
                appended = current + "-" + parts[idx]
                if os.path.isdir(appended) or _has_prefix(appended):
                    _search(idx + 1, appended, depth + 1)

    _search(1, "/" + parts[0], 0)
    return best


def _has_prefix(path: str) -> bool:
    """Check if path is a prefix of any existing directory (parent exists)."""
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        return False
    basename = os.path.basename(path)
    try:
        entries = os.listdir(parent)
    except OSError:
        return False
    return any(e.startswith(basename) for e in entries)


def extract_cursor_slug_from_path(file_path: str) -> str | None:
    """Extract project slug from a Cursor file path.

    Paths look like: ~/.cursor/projects/{slug}/agent-transcripts/...
    Returns the slug portion, or None if path doesn't match.
    """
    match = re.search(r"/\.cursor/projects/([^/]+)/", file_path)
    if match:
        return match.group(1)
    return None


def extract_gemini_hash_from_path(file_path: str) -> str | None:
    """Extract project hash from a Gemini CLI file path.

    Paths look like: ~/.gemini/tmp/{hash}/chats/session-*.json
    Returns the hash portion, or None if path doesn't match.
    """
    match = re.search(r"/\.gemini/tmp/([^/]+)/chats/", file_path)
    if match:
        return match.group(1)
    return None


def _git_cmd(cwd: str, cmd: list[str]) -> str | None:
    """Run a git command in the given directory.

    Returns stripped stdout on success, None on any failure.
    Uses subprocess.run with timeout=5.
    """
    try:
        result = subprocess.run(
            ["git", "-C", cwd, *cmd],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _extract_repo_name(url: str) -> str | None:
    """Parse 'org/repo' from a git remote URL.

    Handles:
    - SSH: git@github.com:org/repo.git
    - HTTPS: https://github.com/org/repo.git
    - SSH with protocol: ssh://git@github.com:22/org/repo.git
    - With or without .git suffix

    Returns 'org/repo' or None if parsing fails.
    """
    # SSH style: git@host:org/repo.git
    ssh_match = re.match(r"^[\w.-]+@[\w.-]+:(.+?)(?:\.git)?$", url)
    if ssh_match:
        return ssh_match.group(1) or None

    # HTTPS or ssh:// style: https://host/org/repo.git or ssh://git@host:port/org/repo.git
    url_match = re.match(r"^(?:https?|ssh)://[^/]+(?::\d+)?/(.+?)(?:\.git)?$", url)
    if url_match:
        return url_match.group(1) or None

    return None
