# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Source-specific collectors that read files and produce NormalizedMessages."""


import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from opentrace.daemon.state import FileState
from opentrace.daemon.watcher import ChangedFile
from opentrace.schemas.claude_code.transform import transform_claude_v1
from opentrace.schemas.codex_cli.transform import (
    CodexTransformContext,
    transform_codex_v1,
)
from opentrace.schemas.cursor.transform import transform_cursor_v1
from opentrace.schemas.cursor.transform_vscdb import transform_cursor_vscdb
from opentrace.schemas.gemini_cli.transform import transform_gemini_v1
from opentrace.schemas.pi.transform import transform_pi_v1
from opentrace.utils.vscdb import load_session, read_item_table, scan_session_timestamps
from opentrace.schemas.unified import NormalizedMessage, SessionContext
from opentrace.utils.cursor_parser import parse_agent_transcript
from opentrace.utils.repo_resolver import (
    _extract_repo_name,
    decode_cursor_slug,
    extract_cursor_slug_from_path,
    extract_gemini_hash_from_path,
    load_repo_cache,
    resolve_repo,
)

logger = logging.getLogger("quickcall.collector")

# Cache CodexTransformContext per file path to avoid replaying from line 0
# on every poll cycle. Stores (last_line_processed, context) tuples.
_codex_context_cache: dict[str, tuple[int, CodexTransformContext]] = {}


@dataclass
class CollectResult:
    """Result from collecting a file."""

    messages: list[NormalizedMessage]
    new_state: FileState


def collect_file(
    changed: ChangedFile,
    existing_state: FileState | None,
    device_name: str | None = None,
    device_id: str | None = None,
    global_email: str | None = None,
    global_name: str | None = None,
    org: str | None = None,
) -> CollectResult:
    """Collect new messages from a changed file using the appropriate strategy."""
    collectors = {
        "claude_code": _collect_claude,
        "codex_cli": _collect_codex,
        "gemini_cli": _collect_gemini,
        "cursor": _collect_cursor,
        "cursor_vscdb": _collect_cursor_vscdb,
        "pi": _collect_pi,
    }
    collector_fn = collectors[changed.source]
    return collector_fn(changed, existing_state, device_name, device_id, global_email, global_name, org)


def _attach_context(messages: list[NormalizedMessage], ctx: SessionContext) -> None:
    """Attach a SessionContext to all messages in-place."""
    for msg in messages:
        msg.session_context = ctx


def _collect_claude(
    changed: ChangedFile,
    existing_state: FileState | None,
    device_name: str | None = None,
    device_id: str | None = None,
    global_email: str | None = None,
    global_name: str | None = None,
    org: str | None = None,
) -> CollectResult:
    """Line-resume collector for Claude Code JSONL files."""
    start_line = existing_state.last_line_processed if existing_state else 0

    # Early exit: if file hasn't grown (no new lines possible), skip opening it
    if existing_state and changed.size == existing_state.last_size:
        new_state = FileState(
            file_path=changed.path,
            source=changed.source,
            last_line_processed=start_line,
            last_mtime=changed.mtime,
            last_size=changed.size,
            retry_count=0,
        )
        return CollectResult(messages=[], new_state=new_state)

    messages: list[NormalizedMessage] = []
    cwd: str | None = None
    git_branch: str | None = None

    with open(changed.path, "r") as f:
        for line_num, raw_line in enumerate(f, start=1):
            if line_num <= start_line:
                continue
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
                if not cwd:
                    cwd = data.get("cwd")
                if not git_branch:
                    git_branch = data.get("gitBranch")
                msgs = transform_claude_v1(data, changed.path, line_num)
                messages.extend(msgs)
            except json.JSONDecodeError as e:
                logger.warning(
                    "Failed to parse line %d of %s: %s", line_num, changed.path, e
                )
                continue
            start_line = line_num

    if messages:
        ctx = _build_session_context(
            cwd=cwd,
            git_branch=git_branch,
            device_name=device_name,
            device_id=device_id,
            global_email=global_email,
            global_name=global_name,
            org=org,
        )
        _attach_context(messages, ctx)

    new_state = FileState(
        file_path=changed.path,
        source=changed.source,
        last_line_processed=start_line,
        last_mtime=changed.mtime,
        last_size=changed.size,
        retry_count=0,
    )
    return CollectResult(messages=messages, new_state=new_state)


def _collect_codex(
    changed: ChangedFile,
    existing_state: FileState | None,
    device_name: str | None = None,
    device_id: str | None = None,
    global_email: str | None = None,
    global_name: str | None = None,
    org: str | None = None,
) -> CollectResult:
    """Line-resume collector for Codex CLI JSONL files with stateful context."""
    start_line = existing_state.last_line_processed if existing_state else 0

    # Early exit: if file hasn't grown (no new lines possible), skip opening it
    if existing_state and changed.size == existing_state.last_size:
        new_state = FileState(
            file_path=changed.path,
            source=changed.source,
            last_line_processed=start_line,
            last_mtime=changed.mtime,
            last_size=changed.size,
            retry_count=0,
        )
        return CollectResult(messages=[], new_state=new_state)

    messages: list[NormalizedMessage] = []

    # Reuse cached context if available and consistent with state, otherwise
    # replay from the beginning to rebuild context.
    cached = _codex_context_cache.get(changed.path)
    if cached and cached[0] == start_line:
        replay_from = start_line
        ctx = cached[1]
    else:
        replay_from = 0
        ctx = CodexTransformContext()

    last_line = start_line

    with open(changed.path, "r") as f:
        for line_num, raw_line in enumerate(f, start=1):
            if line_num <= replay_from:
                continue
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
                msgs = transform_codex_v1(data, changed.path, line_num, ctx)
                if line_num > start_line:
                    messages.extend(msgs)
            except json.JSONDecodeError as e:
                logger.warning(
                    "Failed to parse line %d of %s: %s", line_num, changed.path, e
                )
                continue
            last_line = line_num

    _codex_context_cache[changed.path] = (last_line, ctx)

    if messages:
        session_ctx = _build_session_context(
            cwd=ctx.cwd,
            git_branch=ctx.git_branch,
            git_commit=ctx.git_commit,
            repo_url=ctx.repo_url,
            device_name=device_name,
            device_id=device_id,
            global_email=global_email,
            global_name=global_name,
            org=org,
        )
        _attach_context(messages, session_ctx)

    new_state = FileState(
        file_path=changed.path,
        source=changed.source,
        last_line_processed=last_line,
        last_mtime=changed.mtime,
        last_size=changed.size,
        retry_count=0,
    )
    return CollectResult(messages=messages, new_state=new_state)


def _collect_pi(
    changed: ChangedFile,
    existing_state: FileState | None,
    device_name: str | None = None,
    device_id: str | None = None,
    global_email: str | None = None,
    global_name: str | None = None,
    org: str | None = None,
) -> CollectResult:
    """Line-resume collector for pi.dev JSONL files."""
    start_line = existing_state.last_line_processed if existing_state else 0

    # Early exit: if file hasn't grown, skip opening it
    if existing_state and changed.size == existing_state.last_size:
        new_state = FileState(
            file_path=changed.path,
            source=changed.source,
            last_line_processed=start_line,
            last_mtime=changed.mtime,
            last_size=changed.size,
            retry_count=0,
        )
        return CollectResult(messages=[], new_state=new_state)

    messages: list[NormalizedMessage] = []
    session_id: str | None = None
    cwd: str | None = None
    current_model: str | None = None
    last_line = start_line

    with open(changed.path, "r") as f:
        for line_num, raw_line in enumerate(f, start=1):
            if line_num <= start_line:
                continue
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
                event_type = data.get("type")

                # Extract session metadata from first session event
                if event_type == "session" and not session_id:
                    session_id = data.get("id")
                    cwd = data.get("cwd")

                # Track model changes
                if event_type == "model_change":
                    current_model = data.get("modelId")

                # Skip events until we have a session_id
                if not session_id:
                    last_line = line_num
                    continue

                msgs = transform_pi_v1(
                    data, session_id, changed.path, line_num, current_model
                )
                messages.extend(msgs)
            except json.JSONDecodeError as e:
                logger.warning(
                    "Failed to parse line %d of %s: %s", line_num, changed.path, e
                )
                continue
            last_line = line_num

    if messages:
        ctx = _build_session_context(
            cwd=cwd,
            device_name=device_name,
            device_id=device_id,
            global_email=global_email,
            global_name=global_name,
            org=org,
        )
        _attach_context(messages, ctx)

    new_state = FileState(
        file_path=changed.path,
        source=changed.source,
        last_line_processed=last_line,
        last_mtime=changed.mtime,
        last_size=changed.size,
        retry_count=0,
    )
    return CollectResult(messages=messages, new_state=new_state)


def _collect_gemini(
    changed: ChangedFile,
    existing_state: FileState | None,
    device_name: str | None = None,
    device_id: str | None = None,
    global_email: str | None = None,
    global_name: str | None = None,
    org: str | None = None,
) -> CollectResult:
    """Hash-based collector for Gemini CLI single-JSON session files."""
    content_hash = _hash_file(changed.path)

    # Skip if content hasn't changed
    if existing_state and existing_state.content_hash == content_hash:
        return CollectResult(
            messages=[],
            new_state=FileState(
                file_path=changed.path,
                source=changed.source,
                content_hash=content_hash,
                last_mtime=changed.mtime,
                last_size=changed.size,
                retry_count=0,
            ),
        )

    # Only read file content when we actually need to parse it
    content = _read_file(changed.path)
    messages: list[NormalizedMessage] = []
    project_hash: str | None = None
    try:
        session: dict[str, Any] = json.loads(content)
        project_hash = session.get("projectHash")
        messages = transform_gemini_v1(session, changed.path)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse %s: %s", changed.path, e)

    if not project_hash:
        project_hash = extract_gemini_hash_from_path(changed.path)

    if messages:
        ctx = _build_session_context(
            device_name=device_name,
            device_id=device_id,
            global_email=global_email,
            global_name=global_name,
            org=org,
        )
        ctx.project_hash = project_hash
        _attach_context(messages, ctx)

    new_state = FileState(
        file_path=changed.path,
        source=changed.source,
        content_hash=content_hash,
        last_mtime=changed.mtime,
        last_size=changed.size,
        retry_count=0,
    )
    return CollectResult(messages=messages, new_state=new_state)


def _collect_cursor(
    changed: ChangedFile,
    existing_state: FileState | None,
    device_name: str | None = None,
    device_id: str | None = None,
    global_email: str | None = None,
    global_name: str | None = None,
    org: str | None = None,
) -> CollectResult:
    """Hash-based collector for Cursor agent transcript text files."""
    content_hash = _hash_file(changed.path)

    # Skip if content hasn't changed
    if existing_state and existing_state.content_hash == content_hash:
        return CollectResult(
            messages=[],
            new_state=FileState(
                file_path=changed.path,
                source=changed.source,
                content_hash=content_hash,
                last_mtime=changed.mtime,
                last_size=changed.size,
                retry_count=0,
            ),
        )

    messages: list[NormalizedMessage] = []
    try:
        transcript = parse_agent_transcript(changed.path)
        messages = transform_cursor_v1(transcript, changed.path)
    except Exception as e:
        logger.warning("Failed to parse %s: %s", changed.path, e)

    if messages:
        cwd: str | None = None
        slug = extract_cursor_slug_from_path(changed.path)
        if slug:
            cwd = decode_cursor_slug(slug)

        ctx = _build_session_context(
            cwd=cwd,
            device_name=device_name,
            device_id=device_id,
            global_email=global_email,
            global_name=global_name,
            org=org,
        )
        _attach_context(messages, ctx)

    new_state = FileState(
        file_path=changed.path,
        source=changed.source,
        content_hash=content_hash,
        last_mtime=changed.mtime,
        last_size=changed.size,
        retry_count=0,
    )
    return CollectResult(messages=messages, new_state=new_state)


def _collect_cursor_vscdb(
    changed: ChangedFile,
    existing_state: FileState | None,
    device_name: str | None = None,
    device_id: str | None = None,
    global_email: str | None = None,
    global_name: str | None = None,
    org: str | None = None,
) -> CollectResult:
    """Incremental collector for Cursor state.vscdb (cursorDiskKV) databases.

    Instead of hashing the entire file and re-processing all sessions,
    this does a quick scan of composerData timestamps and only processes
    sessions that are new or have been updated since last poll.
    """
    # 1. Quick-scan all session timestamps
    current_timestamps = scan_session_timestamps(changed.path)

    # 2. Load previous session timestamps from state
    prev_timestamps: dict[str, int] = {}
    if existing_state and existing_state.content_hash:
        try:
            prev_timestamps = json.loads(existing_state.content_hash)
        except (json.JSONDecodeError, TypeError):
            pass

    # 3. Diff: find new or updated sessions
    changed_ids = []
    for cid, ts in current_timestamps.items():
        if cid not in prev_timestamps or prev_timestamps[cid] != ts:
            changed_ids.append(cid)

    # 4. Only load and transform changed sessions
    messages: list[NormalizedMessage] = []
    email = read_item_table(changed.path, "cursorAuth/cachedEmail") if changed_ids else None

    for cid in changed_ids:
        session = load_session(changed.path, cid)
        if session is None:
            continue
        msgs = transform_cursor_vscdb(session)
        cd = session.composer_data
        cwd = _extract_workspace_path(msgs)
        ctx = _build_session_context(
            cwd=cwd,
            global_email=email or global_email,
            git_branch=cd.get("createdOnBranch"),
            device_name=device_name,
            device_id=device_id,
            global_name=global_name,
            org=org,
        )
        _attach_context(msgs, ctx)
        messages.extend(msgs)

    if changed_ids:
        logger.info(
            "cursor_vscdb: %d changed sessions out of %d total, produced %d messages",
            len(changed_ids),
            len(current_timestamps),
            len(messages),
        )

    # 5. Store current timestamps as content_hash (JSON-encoded)
    new_state = FileState(
        file_path=changed.path,
        source=changed.source,
        content_hash=json.dumps(current_timestamps),
        last_mtime=changed.mtime,
        last_size=changed.size,
        retry_count=0,
    )
    return CollectResult(messages=messages, new_state=new_state)


def _build_session_context(
    *,
    cwd: str | None = None,
    git_branch: str | None = None,
    git_commit: str | None = None,
    repo_url: str | None = None,
    device_name: str | None = None,
    device_id: str | None = None,
    global_email: str | None = None,
    global_name: str | None = None,
    org: str | None = None,
) -> SessionContext:
    """Build a SessionContext by resolving repo info from cwd.

    Identity chain: local git config > global git config > device_name.
    Pre-provided git fields (from source data) take priority over resolved ones.
    """
    repo_info = None
    if cwd:
        try:
            repo_info = resolve_repo(cwd)
        except Exception as e:
            logger.debug("Failed to resolve repo for %s: %s", cwd, e)

    resolved_repo_url = repo_info.repo_url if repo_info else None
    resolved_repo_name = repo_info.repo_name if repo_info else None

    # Derive repo_name from repo_url when resolve_repo didn't find one
    final_repo_url = repo_url or resolved_repo_url
    final_repo_name = resolved_repo_name
    if not final_repo_name and final_repo_url:
        final_repo_name = _extract_repo_name(final_repo_url)

    # Fall back to repo cache if still no repo_name
    if not final_repo_name and cwd:
        try:
            cache = load_repo_cache()
            final_repo_name = cache.get(cwd)
        except Exception:
            pass

    return SessionContext(
        user_email=(repo_info.user_email if repo_info else None) or global_email,
        user_name=(repo_info.user_name if repo_info else None) or global_name,
        device_name=device_name,
        device_id=device_id,
        cwd=cwd,
        repo_url=final_repo_url,
        repo_name=final_repo_name,
        git_branch=git_branch or (repo_info.git_branch if repo_info else None),
        git_commit=git_commit or (repo_info.git_commit if repo_info else None),
        org=org,
    )


def extract_session_meta(file_path: str, source: str) -> tuple[str | None, str | None]:
    """Lightweight extraction of (session_id, cwd) from a file without full parsing.

    Used by backfill to resolve git metadata for previously-processed sessions.
    """
    if source == "claude_code":
        return _extract_meta_claude(file_path)
    elif source == "codex_cli":
        return _extract_meta_codex(file_path)
    elif source == "cursor":
        return _extract_meta_cursor(file_path)
    elif source == "pi":
        return _extract_meta_pi(file_path)
    return None, None


def _extract_meta_claude(file_path: str) -> tuple[str | None, str | None]:
    """Extract session_id and cwd from first ~10 lines of a Claude Code JSONL file."""
    session_id: str | None = None
    cwd: str | None = None
    try:
        with open(file_path, "r") as f:
            for i, line in enumerate(f):
                if i >= 10:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if not session_id:
                        session_id = data.get("sessionId")
                    if not cwd:
                        cwd = data.get("cwd")
                    if session_id and cwd:
                        break
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return session_id, cwd


def _extract_meta_codex(file_path: str) -> tuple[str | None, str | None]:
    """Extract session_id and cwd from first ~10 lines of a Codex CLI JSONL file."""
    session_id: str | None = None
    cwd: str | None = None
    try:
        with open(file_path, "r") as f:
            for i, line in enumerate(f):
                if i >= 10:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if not session_id:
                        session_id = data.get("id") or data.get("session_id")
                    if not cwd:
                        cwd = data.get("cwd")
                    if session_id and cwd:
                        break
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return session_id, cwd


def _extract_meta_cursor(file_path: str) -> tuple[str | None, str | None]:
    """Extract session_id and cwd from a Cursor transcript file path."""
    session_id: str | None = None
    cwd: str | None = None

    match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", file_path)
    if match:
        session_id = match.group(1)

    slug = extract_cursor_slug_from_path(file_path)
    if slug:
        cwd = decode_cursor_slug(slug)

    return session_id, cwd


def _extract_meta_pi(file_path: str) -> tuple[str | None, str | None]:
    """Extract session_id and cwd from first ~10 lines of a pi.dev JSONL file."""
    session_id: str | None = None
    cwd: str | None = None
    try:
        with open(file_path, "r") as f:
            for i, line in enumerate(f):
                if i >= 10:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("type") == "session":
                        if not session_id:
                            session_id = data.get("id")
                        if not cwd:
                            cwd = data.get("cwd")
                        if session_id and cwd:
                            break
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return session_id, cwd


def _extract_workspace_path(messages: list[NormalizedMessage]) -> str | None:
    """Extract Workspace Path from the first user message's <user_info> block.

    Cursor injects a <user_info> block into the first user turn containing
    'Workspace Path: /path/to/project'. Returns the path or None.
    """
    for msg in messages:
        if msg.msg_type == "user" and msg.content and "Workspace Path:" in msg.content:
            for line in msg.content.split("\n"):
                if line.strip().startswith("Workspace Path:"):
                    path = line.split("Workspace Path:", 1)[1].strip()
                    if path:
                        return path
            break
    return None


def _hash_file(path: str, chunk_size: int = 65536) -> str:
    """Compute SHA-256 hash of a file by streaming chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _read_file(path: str) -> str:
    """Read file contents as string."""
    with open(path, "r") as f:
        return f.read()
