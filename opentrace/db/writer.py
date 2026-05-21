# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Batch COPY writer for NormalizedMessage → PostgreSQL.

Uses a temp-table staging pattern to handle duplicates gracefully:
COPY into temp table → INSERT ... ON CONFLICT DO UPDATE into real table.
"""


import json
import logging
from typing import Sequence

from psycopg import AsyncConnection

from opentrace.schemas.unified import NormalizedMessage

logger = logging.getLogger(__name__)


def _strip_nul(value: str | None) -> str | None:
    """Strip NUL bytes from text before writing to PostgreSQL.

    PostgreSQL text fields reject NUL (0x00) bytes. This can occur
    in tool output from binary files or certain CLI responses.
    """
    if value is None:
        return None
    return value.replace("\x00", "")

SESSION_UPSERT_SQL = (
    "INSERT INTO sessions (id, source, model, user_email, user_name, "
    "device_name, device_id, cwd, repo_url, repo_name, git_branch, git_commit, "
    "project_hash, org, raw_file_path, org_id, first_seen, last_updated) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (id) DO UPDATE SET "
    "first_seen = LEAST(sessions.first_seen, EXCLUDED.first_seen), "
    "last_updated = GREATEST(sessions.last_updated, EXCLUDED.last_updated), "
    "model = COALESCE(EXCLUDED.model, sessions.model), "
    "user_email = COALESCE(EXCLUDED.user_email, sessions.user_email), "
    "user_name = COALESCE(EXCLUDED.user_name, sessions.user_name), "
    "device_name = COALESCE(EXCLUDED.device_name, sessions.device_name), "
    "device_id = COALESCE(EXCLUDED.device_id, sessions.device_id), "
    "cwd = COALESCE(EXCLUDED.cwd, sessions.cwd), "
    "repo_url = COALESCE(EXCLUDED.repo_url, sessions.repo_url), "
    "repo_name = COALESCE(EXCLUDED.repo_name, sessions.repo_name), "
    "git_branch = COALESCE(EXCLUDED.git_branch, sessions.git_branch), "
    "git_commit = COALESCE(EXCLUDED.git_commit, sessions.git_commit), "
    "project_hash = COALESCE(EXCLUDED.project_hash, sessions.project_hash), "
    "org = COALESCE(EXCLUDED.org, sessions.org), "
    "raw_file_path = COALESCE(EXCLUDED.raw_file_path, sessions.raw_file_path), "
    "org_id = COALESCE(EXCLUDED.org_id, sessions.org_id)"
)


async def _upsert_sessions(
    conn: AsyncConnection,
    messages: Sequence[NormalizedMessage],
) -> None:
    """Ensure all referenced sessions exist with timestamps from messages."""
    # Collect best context per session and compute min/max timestamps
    seen: dict[str, NormalizedMessage] = {}
    first_seen: dict[str, str] = {}
    last_updated: dict[str, str] = {}

    for msg in messages:
        sid = msg.session_id
        ts = msg.timestamp
        if sid not in seen:
            seen[sid] = msg
        elif msg.model and not seen[sid].model:
            seen[sid] = msg

        if ts:
            if sid not in first_seen or ts < first_seen[sid]:
                first_seen[sid] = ts
            if sid not in last_updated or ts > last_updated[sid]:
                last_updated[sid] = ts

    if not seen:
        return

    async with conn.cursor() as cur:
        for sid, msg in seen.items():
            ctx = msg.session_context
            await cur.execute(
                SESSION_UPSERT_SQL,
                (
                    sid,
                    msg.source,
                    msg.model,
                    ctx.user_email if ctx else None,
                    ctx.user_name if ctx else None,
                    ctx.device_name if ctx else None,
                    ctx.device_id if ctx else None,
                    ctx.cwd if ctx else None,
                    ctx.repo_url if ctx else None,
                    ctx.repo_name if ctx else None,
                    ctx.git_branch if ctx else None,
                    ctx.git_commit if ctx else None,
                    ctx.project_hash if ctx else None,
                    ctx.org if ctx else None,
                    msg.raw_file_path or None,
                    None,  # org_id — resolved only in server handlers
                    first_seen.get(sid),
                    last_updated.get(sid),
                ),
            )


async def _copy_messages(
    conn: AsyncConnection,
    messages: Sequence[NormalizedMessage],
) -> int:
    """Batch-insert messages using COPY via temp table to skip duplicates.

    Returns the number of rows actually inserted (after dedup).
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "CREATE TEMP TABLE _stg_messages (LIKE messages INCLUDING DEFAULTS) "
            "ON COMMIT DROP"
        )
        async with cur.copy(
            "COPY _stg_messages (id, session_id, source, source_schema_version, "
            "msg_type, timestamp, content, thinking, model, raw_data, "
            "raw_file_path, raw_line_number) FROM STDIN"
        ) as copy:
            for msg in messages:
                raw_data_json = json.dumps(msg.raw_data) if msg.raw_data else None
                content = msg.content if isinstance(msg.content, str) or msg.content is None else json.dumps(msg.content)
                thinking = msg.thinking if isinstance(msg.thinking, str) or msg.thinking is None else json.dumps(msg.thinking)
                await copy.write_row((
                    msg.id,
                    msg.session_id,
                    msg.source,
                    msg.source_schema_version,
                    msg.msg_type,
                    msg.timestamp or None,
                    _strip_nul(content),
                    _strip_nul(thinking),
                    msg.model,
                    raw_data_json,
                    msg.raw_file_path or None,
                    msg.raw_line_number,
                ))
        await cur.execute(
            "DELETE FROM _stg_messages WHERE ctid NOT IN "
            "(SELECT DISTINCT ON (id) ctid FROM _stg_messages ORDER BY id, ctid DESC)"
        )
        await cur.execute(
            "INSERT INTO messages (id, session_id, source, source_schema_version, "
            "msg_type, timestamp, content, thinking, model, raw_data, "
            "raw_file_path, raw_line_number, ingested_at) "
            "SELECT id, session_id, source, source_schema_version, "
            "msg_type, timestamp, content, thinking, model, raw_data, "
            "raw_file_path, raw_line_number, ingested_at "
            "FROM _stg_messages "
            "ON CONFLICT (id) DO UPDATE SET "
            "source_schema_version = EXCLUDED.source_schema_version, "
            "msg_type = EXCLUDED.msg_type, "
            "timestamp = COALESCE(EXCLUDED.timestamp, messages.timestamp), "
            "content = COALESCE(EXCLUDED.content, messages.content), "
            "thinking = COALESCE(EXCLUDED.thinking, messages.thinking), "
            "model = COALESCE(EXCLUDED.model, messages.model), "
            "raw_data = COALESCE(EXCLUDED.raw_data, messages.raw_data)"
        )
        return cur.rowcount


async def _copy_token_usage(
    conn: AsyncConnection,
    messages: Sequence[NormalizedMessage],
) -> None:
    """Batch-insert token usage rows, skipping duplicates."""
    rows = [
        msg for msg in messages
        if msg.tokens and (
            msg.tokens.input or msg.tokens.output
            or msg.tokens.cached or msg.tokens.thinking
        )
    ]
    if not rows:
        return

    async with conn.cursor() as cur:
        await cur.execute(
            "CREATE TEMP TABLE _stg_token_usage (LIKE token_usage INCLUDING DEFAULTS) "
            "ON COMMIT DROP"
        )
        async with cur.copy(
            "COPY _stg_token_usage (message_id, input_tokens, output_tokens, "
            "cached_tokens, thinking_tokens) FROM STDIN"
        ) as copy:
            for msg in rows:
                await copy.write_row((
                    msg.id,
                    msg.tokens.input,
                    msg.tokens.output,
                    msg.tokens.cached,
                    msg.tokens.thinking,
                ))
        await cur.execute(
            "DELETE FROM _stg_token_usage WHERE ctid NOT IN "
            "(SELECT DISTINCT ON (message_id) ctid FROM _stg_token_usage ORDER BY message_id, ctid DESC)"
        )
        await cur.execute(
            "INSERT INTO token_usage (message_id, input_tokens, output_tokens, "
            "cached_tokens, thinking_tokens) "
            "SELECT message_id, input_tokens, output_tokens, "
            "cached_tokens, thinking_tokens "
            "FROM _stg_token_usage "
            "ON CONFLICT (message_id) DO UPDATE SET "
            "input_tokens = EXCLUDED.input_tokens, "
            "output_tokens = EXCLUDED.output_tokens, "
            "cached_tokens = EXCLUDED.cached_tokens, "
            "thinking_tokens = EXCLUDED.thinking_tokens"
        )


async def _copy_tool_calls(
    conn: AsyncConnection,
    messages: Sequence[NormalizedMessage],
) -> None:
    """Batch-insert tool_call rows, skipping duplicates."""
    rows = [msg for msg in messages if msg.tool_call is not None]
    if not rows:
        return

    async with conn.cursor() as cur:
        await cur.execute(
            "CREATE TEMP TABLE _stg_tool_calls (LIKE tool_calls INCLUDING DEFAULTS) "
            "ON COMMIT DROP"
        )
        async with cur.copy(
            "COPY _stg_tool_calls (message_id, tool_id, tool_name, tool_input) "
            "FROM STDIN"
        ) as copy:
            for msg in rows:
                tc = msg.tool_call
                tool_input_json = json.dumps(tc.input) if tc.input else None
                await copy.write_row((
                    msg.id,
                    tc.id,
                    tc.name,
                    tool_input_json,
                ))
        await cur.execute(
            "DELETE FROM _stg_tool_calls WHERE ctid NOT IN "
            "(SELECT DISTINCT ON (message_id) ctid FROM _stg_tool_calls ORDER BY message_id, ctid DESC)"
        )
        await cur.execute(
            "INSERT INTO tool_calls (message_id, tool_id, tool_name, tool_input) "
            "SELECT message_id, tool_id, tool_name, tool_input "
            "FROM _stg_tool_calls "
            "ON CONFLICT (message_id) DO UPDATE SET "
            "tool_id = EXCLUDED.tool_id, "
            "tool_name = EXCLUDED.tool_name, "
            "tool_input = EXCLUDED.tool_input"
        )


async def _copy_tool_results(
    conn: AsyncConnection,
    messages: Sequence[NormalizedMessage],
) -> None:
    """Batch-insert tool_result rows, skipping duplicates."""
    rows = [msg for msg in messages if msg.tool_result is not None]
    if not rows:
        return

    async with conn.cursor() as cur:
        await cur.execute(
            "CREATE TEMP TABLE _stg_tool_results (LIKE tool_results INCLUDING DEFAULTS) "
            "ON COMMIT DROP"
        )
        async with cur.copy(
            "COPY _stg_tool_results (message_id, call_id, output, status) "
            "FROM STDIN"
        ) as copy:
            for msg in rows:
                tr = msg.tool_result
                output = tr.output
                if not isinstance(output, str):
                    output = json.dumps(output) if output is not None else None
                await copy.write_row((
                    msg.id,
                    tr.call_id,
                    _strip_nul(output),
                    tr.status,
                ))
        await cur.execute(
            "DELETE FROM _stg_tool_results WHERE ctid NOT IN "
            "(SELECT DISTINCT ON (message_id) ctid FROM _stg_tool_results ORDER BY message_id, ctid DESC)"
        )
        await cur.execute(
            "INSERT INTO tool_results (message_id, call_id, output, status) "
            "SELECT message_id, call_id, output, status "
            "FROM _stg_tool_results "
            "ON CONFLICT (message_id) DO UPDATE SET "
            "call_id = EXCLUDED.call_id, "
            "output = EXCLUDED.output, "
            "status = EXCLUDED.status"
        )


class BatchWriter:
    """Writes batches of NormalizedMessage to PostgreSQL using async COPY.

    Usage::

        async with pool.connection() as conn:
            writer = BatchWriter(conn)
            await writer.write(messages)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def write(self, messages: Sequence[NormalizedMessage]) -> int:
        """Write a batch of messages to the database.

        Returns the number of messages actually inserted (after dedup).
        """
        if not messages:
            return 0

        try:
            await _upsert_sessions(self._conn, messages)
            inserted = await _copy_messages(self._conn, messages)
            await _copy_token_usage(self._conn, messages)
            await _copy_tool_calls(self._conn, messages)
            await _copy_tool_results(self._conn, messages)
            await self._conn.commit()
        except Exception:
            logger.exception("BatchWriter.write() failed for %d messages", len(messages))
            await self._conn.rollback()
            raise

        return inserted
