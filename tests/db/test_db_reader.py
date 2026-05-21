# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for db.reader module (C3)."""


from unittest.mock import AsyncMock


from opentrace.db.reader import get_feed, get_file_sync_state, get_messages, get_sessions, get_stats


def _mock_conn_multi(execute_returns: list):
    """Create a mock conn where cursor.execute() is called multiple times.

    Each item in execute_returns is either a dict (for fetchone) or a list (for fetchall).
    reader.py uses: async with conn.cursor(row_factory=...) as cur: await cur.execute(...)
    """
    conn = AsyncMock()

    cur = AsyncMock()
    results = []
    for ret in execute_returns:
        mock_result = AsyncMock()
        if isinstance(ret, dict):
            mock_result.fetchone = AsyncMock(return_value=ret)
        else:
            mock_result.fetchall = AsyncMock(return_value=ret)
        results.append(mock_result)
    cur.execute = AsyncMock(side_effect=results)
    # conn.cursor() returns an async context manager yielding cur
    conn.cursor = lambda **kwargs: _async_cm(cur)
    return conn


def _mock_conn(fetchall_return: list):
    """Create a mock conn for a single cursor.execute().fetchall() call."""
    conn = AsyncMock()
    cur = AsyncMock()
    mock_result = AsyncMock()
    mock_result.fetchall = AsyncMock(return_value=fetchall_return)
    cur.execute = AsyncMock(return_value=mock_result)
    conn.cursor = lambda **kwargs: _async_cm(cur)
    # Expose cur.execute as conn._cur_execute for test assertions
    conn._cur = cur
    return conn


class _async_cm:
    """Simple async context manager wrapper for mock cursors."""
    def __init__(self, obj):
        self._obj = obj
    async def __aenter__(self):
        return self._obj
    async def __aexit__(self, *args):
        pass


class TestGetStats:
    async def test_returns_aggregate_stats(self):
        total_sessions = {"n": 5}
        total_messages = {"n": 100}
        by_source = [{"source": "claude_code", "count": 80}, {"source": "gemini_cli", "count": 20}]
        by_type = [{"msg_type": "assistant", "count": 50}, {"msg_type": "user", "count": 50}]
        token_totals = {"input": 1000, "output": 500, "cached": 200, "thinking": 100}
        by_org = [{"org": "test-org", "session_count": 5, "message_count": 100}]

        conn = _mock_conn_multi([total_sessions, total_messages, by_source, by_type, token_totals, by_org])

        result = await get_stats(conn)

        assert result["total_sessions"] == 5
        assert result["total_messages"] == 100
        assert len(result["by_source"]) == 2
        assert result["by_source"][0]["source"] == "claude_code"
        assert len(result["by_type"]) == 2
        assert result["tokens"]["input"] == 1000
        assert len(result["by_org"]) == 1
        assert result["by_org"][0]["org"] == "test-org"


class TestGetSessions:
    async def test_returns_sessions_list(self):
        rows = [
            {"id": "sess-1", "source": "claude_code", "message_count": 10, "latest_message": "2026-02-06T10:00:00Z"},
            {"id": "sess-2", "source": "gemini_cli", "message_count": 5, "latest_message": "2026-02-06T11:00:00Z"},
        ]
        conn = _mock_conn(rows)

        result = await get_sessions(conn)
        assert len(result) == 2
        assert result[0]["id"] == "sess-1"

    async def test_filters_by_source(self):
        rows = [{"id": "sess-1", "source": "claude_code", "message_count": 10}]
        conn = _mock_conn(rows)

        result = await get_sessions(conn, source="claude_code")
        assert len(result) == 1
        # Verify the SQL was called with the source param
        call_args = conn._cur.execute.call_args
        assert "claude_code" in call_args[0][1]

    async def test_respects_limit_and_offset(self):
        conn = _mock_conn([])
        await get_sessions(conn, limit=10, offset=5)
        call_args = conn._cur.execute.call_args
        assert 10 in call_args[0][1]
        assert 5 in call_args[0][1]

    async def test_uses_correlated_subqueries_not_cte(self):
        """Fix #1: correlated subqueries scan only ~50 sessions instead of full messages table."""
        conn = _mock_conn([])
        await get_sessions(conn)
        sql = conn._cur.execute.call_args[0][0]
        assert "WITH msg_stats AS" not in sql, "CTE causes full table scan — use correlated subqueries"
        assert "(SELECT count(*) FROM messages m WHERE m.session_id = s.id)" in sql
        assert "(SELECT max(timestamp) FROM messages m WHERE m.session_id = s.id)" in sql

    async def test_filters_by_date(self):
        conn = _mock_conn([])
        await get_sessions(conn, date="2026-04-16")
        sql = conn._cur.execute.call_args[0][0]
        assert "s.last_updated >= %s::date" in sql
        assert "s.last_updated < (%s::date + interval '1 day')" in sql
        call_args = conn._cur.execute.call_args
        assert "2026-04-16" in call_args[0][1]


class TestGetMessages:
    async def test_returns_messages_for_session(self):
        rows = [
            {"id": "msg-1", "session_id": "sess-1", "msg_type": "user", "content": "hello"},
            {"id": "msg-2", "session_id": "sess-1", "msg_type": "assistant", "content": "hi"},
        ]
        conn = _mock_conn(rows)

        result = await get_messages(conn, session_id="sess-1")
        assert len(result) == 2
        assert result[0]["id"] == "msg-1"

    async def test_passes_session_id_param(self):
        conn = _mock_conn([])
        await get_messages(conn, session_id="test-session")
        call_args = conn._cur.execute.call_args
        assert "test-session" in call_args[0][1]


class TestGetFileSyncState:
    async def test_returns_sync_state(self):
        rows = [
            {"raw_file_path": "/tmp/a.jsonl", "source": "claude_code", "message_count": 42, "max_line": 150, "last_line_read": 169},
            {"raw_file_path": "/tmp/b.json", "source": "gemini_cli", "message_count": 10, "max_line": 0, "last_line_read": 0},
        ]
        conn = _mock_conn(rows)

        result = await get_file_sync_state(conn)
        assert len(result) == 2
        assert result[0]["raw_file_path"] == "/tmp/a.jsonl"
        assert result[0]["max_line"] == 150
        assert result[0]["last_line_read"] == 169

    async def test_returns_empty_list(self):
        conn = _mock_conn([])
        result = await get_file_sync_state(conn)
        assert result == []

    async def test_last_line_read_defaults_to_zero(self):
        rows = [
            {"raw_file_path": "/tmp/c.jsonl", "source": "codex_cli", "message_count": 5, "max_line": 10, "last_line_read": 0},
        ]
        conn = _mock_conn(rows)

        result = await get_file_sync_state(conn)
        assert result[0]["last_line_read"] == 0


class TestGetFeed:
    async def test_returns_feed_without_since(self):
        rows = [
            {"id": "msg-1", "session_id": "sess-1", "msg_type": "user", "content_preview": "hello"},
        ]
        conn = _mock_conn(rows)

        result = await get_feed(conn)
        assert len(result) == 1

    async def test_returns_feed_with_since(self):
        rows = [
            {"id": "msg-2", "session_id": "sess-1", "msg_type": "assistant", "content_preview": "hi"},
        ]
        conn = _mock_conn(rows)

        result = await get_feed(conn, since="2026-02-06T10:00:00Z")
        assert len(result) == 1
        # Verify the since param was passed
        call_args = conn._cur.execute.call_args
        assert "2026-02-06T10:00:00Z" in call_args[0][1]

    async def test_respects_limit(self):
        conn = _mock_conn([])
        await get_feed(conn, limit=5)
        call_args = conn._cur.execute.call_args
        assert 5 in call_args[0][1]
