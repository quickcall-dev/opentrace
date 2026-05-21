# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Read-only queries for the dashboard API."""


from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row


async def get_stats(
    conn: AsyncConnection, org: str | None = None
) -> dict[str, Any]:
    """Aggregate stats: totals, by source, by msg_type, token sums."""
    # Build org filter fragments
    session_where = " WHERE org = %s" if org else ""
    session_params: list[Any] = [org] if org else []

    msg_join = ""
    msg_where = ""
    msg_params: list[Any] = []
    if org:
        msg_join = " JOIN sessions s ON s.id = m.session_id"
        msg_where = " WHERE s.org = %s"
        msg_params = [org]

    token_join = ""
    token_where = ""
    token_params: list[Any] = []
    if org:
        token_join = (
            " JOIN messages m ON m.id = tu.message_id"
            " JOIN sessions s ON s.id = m.session_id"
        )
        token_where = " WHERE s.org = %s"
        token_params = [org]

    async with conn.cursor(row_factory=dict_row) as cur:
        total_sessions = await (await cur.execute(
            "SELECT count(*) AS n FROM sessions" + session_where, session_params
        )).fetchone()

        total_messages = await (await cur.execute(
            "SELECT count(*) AS n FROM messages m" + msg_join + msg_where,
            msg_params,
        )).fetchone()

        by_source = await (await cur.execute(
            "SELECT m.source, count(*) AS count FROM messages m"
            + msg_join + msg_where
            + " GROUP BY m.source ORDER BY count DESC",
            msg_params,
        )).fetchall()

        by_type = await (await cur.execute(
            "SELECT m.msg_type, count(*) AS count FROM messages m"
            + msg_join + msg_where
            + " GROUP BY m.msg_type ORDER BY count DESC",
            msg_params,
        )).fetchall()

        token_totals = await (await cur.execute(
            "SELECT coalesce(sum(tu.input_tokens),0) AS input, "
            "coalesce(sum(tu.output_tokens),0) AS output, "
            "coalesce(sum(tu.cached_tokens),0) AS cached, "
            "coalesce(sum(tu.thinking_tokens),0) AS thinking "
            "FROM token_usage tu" + token_join + token_where,
            token_params,
        )).fetchone()

        by_org = await (await cur.execute(
            "SELECT coalesce(s.org, 'unknown') AS org, "
            "count(DISTINCT s.id) AS session_count, "
            "count(m.id) AS message_count "
            "FROM sessions s LEFT JOIN messages m ON m.session_id = s.id"
            + (" WHERE s.org = %s" if org else "")
            + " GROUP BY coalesce(s.org, 'unknown') ORDER BY session_count DESC",
            [org] if org else [],
        )).fetchall()

    return {
        "total_sessions": total_sessions["n"],
        "total_messages": total_messages["n"],
        "by_source": by_source,
        "by_type": by_type,
        "by_org": by_org,
        "tokens": token_totals,
    }


async def get_sessions(
    conn: AsyncConnection,
    source: str | None = None,
    session_id: str | None = None,
    org: str | None = None,
    date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List sessions with message count and latest timestamp.

    Uses correlated subqueries so PostgreSQL only scans messages for the
    ~50 sessions in the result set, avoiding a full-table aggregate.
    """
    params: list[Any] = []
    conditions: list[str] = []

    if source:
        conditions.append("s.source = %s")
        params.append(source)
    if session_id:
        conditions.append("s.id = %s")
        params.append(session_id)
    if org:
        conditions.append("s.org = %s")
        params.append(org)
    if date:
        conditions.append("s.last_updated >= %s::date AND s.last_updated < (%s::date + interval '1 day')")
        params.append(date)
        params.append(date)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions) + " "

    query = (
        "SELECT s.id, s.source, s.model, s.first_seen, s.last_updated, "
        "s.user_email, s.user_name, s.device_name, s.device_id, s.cwd, "
        "s.repo_url, s.repo_name, s.git_branch, s.git_commit, s.project_hash, s.org, "
        "(SELECT count(*) FROM messages m WHERE m.session_id = s.id) AS message_count, "
        "(SELECT max(timestamp) FROM messages m WHERE m.session_id = s.id) AS latest_message "
        "FROM sessions s "
        + where_clause +
        "ORDER BY s.last_updated DESC LIMIT %s OFFSET %s"
    )
    params.extend([limit, offset])

    async with conn.cursor(row_factory=dict_row) as cur:
        return await (await cur.execute(query, params)).fetchall()


async def get_messages(
    conn: AsyncConnection,
    session_id: str,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Messages for a session with token and tool info."""
    async with conn.cursor(row_factory=dict_row) as cur:
        rows = await (await cur.execute(
            "SELECT m.id, m.session_id, m.source, m.msg_type, m.timestamp, "
            "m.content, m.thinking, m.model, m.raw_line_number, "
            "t.input_tokens, t.output_tokens, t.cached_tokens, t.thinking_tokens, "
            "tc.tool_name, tc.tool_input, "
            "tr.output AS tool_output, tr.status AS tool_status "
            "FROM messages m "
            "LEFT JOIN token_usage t ON t.message_id = m.id "
            "LEFT JOIN tool_calls tc ON tc.message_id = m.id "
            "LEFT JOIN tool_results tr ON tr.message_id = m.id "
            "WHERE m.session_id = %s "
            "ORDER BY m.timestamp ASC, m.raw_line_number ASC "
            "LIMIT %s OFFSET %s",
            [session_id, limit, offset],
        )).fetchall()

    return rows


async def get_file_sync_state(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Return max raw_line_number, message count, and last_line_read per raw_file_path.

    Uses FULL OUTER JOIN so that file_progress entries (daemon's reported position)
    are returned even when no messages exist yet for that file (e.g. ON CONFLICT
    deduplication ate them all). This is critical for correct reconciliation.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        rows = await (await cur.execute(
            "SELECT "
            "  COALESCE(m.raw_file_path, fp.raw_file_path) AS raw_file_path, "
            "  COALESCE(m.source, fp.source) AS source, "
            "  COALESCE(m.message_count, 0) AS message_count, "
            "  COALESCE(m.max_line, 0) AS max_line, "
            "  COALESCE(fp.last_line_read, 0) AS last_line_read, "
            "  fp.content_hash AS content_hash "
            "FROM ("
            "  SELECT raw_file_path, source, count(*) AS message_count, "
            "    COALESCE(max(raw_line_number), 0) AS max_line "
            "  FROM messages "
            "  WHERE raw_file_path IS NOT NULL "
            "  GROUP BY raw_file_path, source"
            ") m "
            "FULL OUTER JOIN file_progress fp "
            "  ON fp.raw_file_path = m.raw_file_path AND fp.source = m.source"
        )).fetchall()

    return rows


async def get_orgs(conn: AsyncConnection) -> list[str]:
    """Return distinct org values from sessions."""
    async with conn.cursor(row_factory=dict_row) as cur:
        rows = await (await cur.execute(
            "SELECT DISTINCT org FROM sessions WHERE org IS NOT NULL ORDER BY org"
        )).fetchall()
    return [r["org"] for r in rows]


async def get_feed(
    conn: AsyncConnection,
    since: str | None = None,
    org: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Latest messages across all sessions (for live feed)."""
    base = (
        "SELECT m.id, m.session_id, m.source, m.msg_type, m.timestamp, "
        "left(m.content, 200) AS content_preview, m.model, "
        "t.input_tokens, t.output_tokens, s.device_name "
        "FROM messages m "
        "LEFT JOIN token_usage t ON t.message_id = m.id "
        "JOIN sessions s ON s.id = m.session_id "
    )
    conditions: list[str] = []
    params: list[Any] = []

    if org:
        conditions.append("s.org = %s")
        params.append(org)
    if since:
        conditions.append("m.ingested_at > %s")
        params.append(since)

    if conditions:
        base += "WHERE " + " AND ".join(conditions) + " "

    base += "ORDER BY m.ingested_at DESC LIMIT %s"
    params.append(limit)

    async with conn.cursor(row_factory=dict_row) as cur:
        rows = await (await cur.execute(base, params)).fetchall()

    return rows
