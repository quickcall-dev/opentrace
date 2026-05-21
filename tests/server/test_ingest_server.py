# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for the ingest server.

Tests the batch accumulator, HTTP handlers, and request parsing.
No Postgres required — all DB interactions are mocked.
"""


import asyncio
import json
import http.client
import threading
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from opentrace.schemas.unified import NormalizedMessage
from opentrace.server.batch import BatchAccumulator
from opentrace.server.handlers import (
    handle_api_feed,
    handle_api_messages,
    handle_api_monitor,
    handle_api_sessions,
    handle_api_stats,
    handle_api_sync,
    handle_file_progress,
    handle_file_progress_bulk,
    handle_health,
    handle_ingest,
    handle_sessions,
    _dict_to_normalized_message,
    _parse_qs,
    _serialize_row,
    _validate_message_dict,
)
from opentrace.server.app import create_server


# ── Async context manager helper for cursor mocks ─────────────────────


class _async_cm:
    """Simple async context manager wrapper for mock cursors."""
    def __init__(self, obj):
        self._obj = obj
    async def __aenter__(self):
        return self._obj
    async def __aexit__(self, *args):
        pass


def _mock_conn_with_cursor(fetchall_return=None, fetchone_return=None):
    """Create a mock conn using cursor-based pattern (for reader functions).

    Reader functions use: async with conn.cursor(row_factory=...) as cur:
    """
    mock_conn = AsyncMock()
    cur = AsyncMock()
    mock_result = AsyncMock()
    if fetchall_return is not None:
        mock_result.fetchall = AsyncMock(return_value=fetchall_return)
    if fetchone_return is not None:
        mock_result.fetchone = AsyncMock(return_value=fetchone_return)
    cur.execute = AsyncMock(return_value=mock_result)
    mock_conn.cursor = lambda **kwargs: _async_cm(cur)
    mock_conn._cur = cur
    return mock_conn


def _mock_conn_with_cursor_multi(execute_returns):
    """Create a mock conn for multiple cursor.execute() calls (e.g. get_stats).

    Each item in execute_returns is either a dict (fetchone) or a list (fetchall).
    """
    mock_conn = AsyncMock()
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
    mock_conn.cursor = lambda **kwargs: _async_cm(cur)
    mock_conn._cur = cur
    return mock_conn


# ── Fixtures ──────────────────────────────────────────────────────────


def _sample_message_dict(**overrides) -> dict:
    base = {
        "id": "msg-001",
        "session_id": "sess-001",
        "source": "claude_code",
        "source_schema_version": 1,
        "msg_type": "assistant",
        "timestamp": "2026-02-06T10:00:00Z",
        "content": "Hello, world!",
        "tokens": {"input": 100, "output": 50, "cached": 0, "thinking": 0},
        "tool_call": None,
        "tool_result": None,
        "thinking": None,
        "model": "claude-sonnet-4-5-20250929",
        "raw_file_path": "/home/user/.claude/projects/test/abc.jsonl",
        "raw_line_number": 5,
    }
    base.update(overrides)
    return base


def _sample_normalized_message(**overrides) -> NormalizedMessage:
    return _dict_to_normalized_message(_sample_message_dict(**overrides))


# ── BatchAccumulator tests ────────────────────────────────────────────


class TestBatchAccumulator:
    @pytest.fixture
    def flush_mock(self):
        mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        return mock

    async def test_add_messages(self, flush_mock):
        acc = BatchAccumulator(flush_callback=flush_mock, batch_size=10)
        try:
            msgs = [_sample_normalized_message(id=f"msg-{i}") for i in range(3)]
            count = await acc.add(msgs)
            assert count == 3
            assert acc.pending == 3
            flush_mock.assert_not_called()
        finally:
            await acc.close()

    async def test_flush_on_batch_size(self, flush_mock):
        acc = BatchAccumulator(flush_callback=flush_mock, batch_size=5)
        try:
            msgs = [_sample_normalized_message(id=f"msg-{i}") for i in range(5)]
            await acc.add(msgs)
            flush_mock.assert_called_once()
            assert acc.pending == 0
            assert acc.total_flushed == 5
        finally:
            await acc.close()

    async def test_manual_flush(self, flush_mock):
        acc = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        try:
            msgs = [_sample_normalized_message(id=f"msg-{i}") for i in range(3)]
            await acc.add(msgs)
            count = await acc.flush()
            assert count == 3
            assert acc.pending == 0
        finally:
            await acc.close()

    async def test_flush_empty_is_noop(self, flush_mock):
        acc = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        try:
            count = await acc.flush()
            assert count == 0
            flush_mock.assert_not_called()
        finally:
            await acc.close()

    async def test_close_flushes_remaining(self, flush_mock):
        acc = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        msgs = [_sample_normalized_message(id=f"msg-{i}") for i in range(3)]
        await acc.add(msgs)
        count = await acc.close()
        assert count == 3
        flush_mock.assert_called_once()

    async def test_add_after_close_raises(self, flush_mock):
        acc = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        await acc.close()
        with pytest.raises(RuntimeError, match="closed"):
            await acc.add([_sample_normalized_message()])

    async def test_timer_flush(self, flush_mock):
        acc = BatchAccumulator(
            flush_callback=flush_mock, batch_size=100, flush_interval=0.1
        )
        try:
            msgs = [_sample_normalized_message()]
            await acc.add(msgs)
            assert acc.pending == 1
            await asyncio.sleep(0.2)
            assert acc.pending == 0
            assert flush_mock.call_count == 1
        finally:
            await acc.close()

    async def test_flush_callback_error_requeues(self):
        call_count = 0

        async def failing_flush(msgs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("DB down")
            return len(msgs)

        acc = BatchAccumulator(flush_callback=failing_flush, batch_size=100)
        try:
            msgs = [_sample_normalized_message()]
            await acc.add(msgs)
            with pytest.raises(RuntimeError, match="DB down"):
                await acc.flush()
            assert acc.pending == 1
            count = await acc.flush()
            assert count == 1
            assert acc.pending == 0
        finally:
            await acc.close()


# ── Handler tests ─────────────────────────────────────────────────────


class TestHandleIngest:
    @pytest.fixture
    def accumulator(self):
        mock_flush = AsyncMock(side_effect=lambda msgs: len(msgs))
        return BatchAccumulator(flush_callback=mock_flush, batch_size=100)

    async def test_valid_single_message(self, accumulator):
        try:
            body = json.dumps([_sample_message_dict()]).encode()
            resp_body, status = await handle_ingest(body, accumulator)
            resp = json.loads(resp_body)
            assert status == 200
            assert resp["ingested"] == 1
        finally:
            await accumulator.close()

    async def test_valid_multiple_messages(self, accumulator):
        try:
            msgs = [_sample_message_dict(id=f"msg-{i}") for i in range(5)]
            body = json.dumps(msgs).encode()
            resp_body, status = await handle_ingest(body, accumulator)
            resp = json.loads(resp_body)
            assert status == 200
            assert resp["ingested"] == 5
        finally:
            await accumulator.close()

    async def test_empty_array(self, accumulator):
        try:
            body = json.dumps([]).encode()
            resp_body, status = await handle_ingest(body, accumulator)
            resp = json.loads(resp_body)
            assert status == 200
            assert resp["ingested"] == 0
        finally:
            await accumulator.close()

    async def test_invalid_json(self, accumulator):
        try:
            resp_body, status = await handle_ingest(b"not json", accumulator)
            resp = json.loads(resp_body)
            assert status == 400
            assert "error" in resp
        finally:
            await accumulator.close()

    async def test_not_an_array(self, accumulator):
        try:
            body = json.dumps({"id": "msg-1"}).encode()
            resp_body, status = await handle_ingest(body, accumulator)
            resp = json.loads(resp_body)
            assert status == 400
            assert "array" in resp["error"]
        finally:
            await accumulator.close()

    async def test_missing_required_fields(self, accumulator):
        try:
            body = json.dumps([{"id": "msg-1"}]).encode()
            resp_body, status = await handle_ingest(body, accumulator)
            resp = json.loads(resp_body)
            assert status == 400
            assert "Missing required fields" in resp["error"]
        finally:
            await accumulator.close()

    async def test_message_with_tool_call(self, accumulator):
        try:
            msg = _sample_message_dict(
                msg_type="tool_call",
                tool_call={"id": "tc-1", "name": "bash", "input": {"cmd": "ls"}},
            )
            body = json.dumps([msg]).encode()
            resp_body, status = await handle_ingest(body, accumulator)
            assert status == 200
        finally:
            await accumulator.close()

    async def test_message_with_tool_result(self, accumulator):
        try:
            msg = _sample_message_dict(
                msg_type="tool_result",
                tool_result={
                    "call_id": "tc-1",
                    "output": "file1.py\nfile2.py",
                    "status": "success",
                },
            )
            body = json.dumps([msg]).encode()
            resp_body, status = await handle_ingest(body, accumulator)
            assert status == 200
        finally:
            await accumulator.close()


def _mock_pool(mock_conn=None, error=None):
    """Create a mock ConnectionPool with an async context manager."""
    pool = MagicMock()
    ctx = AsyncMock()
    if error:
        ctx.__aenter__ = AsyncMock(side_effect=error)
    else:
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.connection = MagicMock(return_value=ctx)
    return pool


class TestHandleSessions:
    async def test_valid_session(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        pool = _mock_pool(mock_conn)

        body = json.dumps({
            "id": "sess-001",
            "source": "claude_code",
            "model": "claude-sonnet-4-5-20250929",
            "raw_file_path": "/path/to/file",
        }).encode()
        resp_body, status = await handle_sessions(body, pool)
        resp = json.loads(resp_body)
        assert status == 200
        assert resp["ok"] is True
        mock_conn.execute.assert_called_once()

    async def test_missing_required_fields(self):
        pool = MagicMock()
        body = json.dumps({"id": "sess-001"}).encode()
        resp_body, status = await handle_sessions(body, pool)
        resp = json.loads(resp_body)
        assert status == 400
        assert "Missing required fields" in resp["error"]

    async def test_invalid_json(self):
        pool = MagicMock()
        resp_body, status = await handle_sessions(b"bad json", pool)
        assert status == 400


class TestHandleFileProgress:
    async def test_valid_upsert(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        pool = _mock_pool(mock_conn)

        body = json.dumps({
            "raw_file_path": "/tmp/a.jsonl",
            "source": "claude_code",
            "last_line_read": 150,
            "content_hash": "abc123",
        }).encode()
        resp_body, status = await handle_file_progress(body, pool)
        resp = json.loads(resp_body)
        assert status == 200
        assert resp["ok"] is True
        mock_conn.execute.assert_called_once()

    async def test_missing_required_fields(self):
        pool = MagicMock()
        body = json.dumps({"raw_file_path": "/tmp/a.jsonl"}).encode()
        resp_body, status = await handle_file_progress(body, pool)
        resp = json.loads(resp_body)
        assert status == 400
        assert "Missing required fields" in resp["error"]

    async def test_invalid_json(self):
        pool = MagicMock()
        resp_body, status = await handle_file_progress(b"bad json", pool)
        assert status == 400

    async def test_without_content_hash(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        pool = _mock_pool(mock_conn)

        body = json.dumps({
            "raw_file_path": "/tmp/a.jsonl",
            "source": "claude_code",
            "last_line_read": 100,
        }).encode()
        resp_body, status = await handle_file_progress(body, pool)
        assert status == 200

    async def test_handles_db_error(self):
        pool = _mock_pool(error=Exception("DB down"))
        body = json.dumps({
            "raw_file_path": "/tmp/a.jsonl",
            "source": "claude_code",
            "last_line_read": 100,
        }).encode()
        resp_body, status = await handle_file_progress(body, pool)
        assert status == 500


class TestHandleApiSync:
    async def test_returns_sync_state(self):
        rows = [
            {"raw_file_path": "/tmp/a.jsonl", "source": "claude_code",
             "message_count": 42, "max_line": 150, "last_line_read": 169},
            {"raw_file_path": "/tmp/b.json", "source": "gemini_cli",
             "message_count": 10, "max_line": 0, "last_line_read": 0},
        ]
        mock_conn = _mock_conn_with_cursor(fetchall_return=rows)
        pool = _mock_pool(mock_conn)

        resp_body, status = await handle_api_sync(pool)
        resp = json.loads(resp_body)
        assert status == 200
        assert len(resp) == 2
        assert resp[0]["raw_file_path"] == "/tmp/a.jsonl"
        assert resp[0]["message_count"] == 42

    async def test_returns_empty_when_no_data(self):
        mock_conn = _mock_conn_with_cursor(fetchall_return=[])
        pool = _mock_pool(mock_conn)

        resp_body, status = await handle_api_sync(pool)
        resp = json.loads(resp_body)
        assert status == 200
        assert resp == []

    async def test_handles_db_error(self):
        pool = _mock_pool(error=Exception("DB down"))
        resp_body, status = await handle_api_sync(pool)
        resp = json.loads(resp_body)
        assert status == 500
        assert "error" in resp


class TestHandleHealth:
    async def test_healthy(self):
        mock_conn = AsyncMock()
        mock_result = AsyncMock()
        mock_result.fetchone = AsyncMock(return_value=(1,))
        mock_conn.execute = AsyncMock(return_value=mock_result)
        pool = _mock_pool(mock_conn)

        resp_body, status = await handle_health(pool)
        resp = json.loads(resp_body)
        assert status == 200
        assert resp["status"] == "ok"
        assert resp["db"] == "connected"

    async def test_unhealthy(self):
        pool = _mock_pool(error=Exception("Connection refused"))
        resp_body, status = await handle_health(pool)
        resp = json.loads(resp_body)
        assert status == 503
        assert resp["status"] == "degraded"
        assert resp["db"] == "disconnected"


# ── Message parsing tests ─────────────────────────────────────────────


class TestDictToNormalizedMessage:
    def test_basic_conversion(self):
        d = _sample_message_dict()
        msg = _dict_to_normalized_message(d)
        assert msg.id == "msg-001"
        assert msg.session_id == "sess-001"
        assert msg.source == "claude_code"
        assert msg.msg_type == "assistant"
        assert msg.content == "Hello, world!"
        assert msg.tokens.input == 100
        assert msg.tokens.output == 50
        assert msg.model == "claude-sonnet-4-5-20250929"

    def test_with_tool_call(self):
        d = _sample_message_dict(
            tool_call={"id": "tc-1", "name": "bash", "input": {"cmd": "ls"}}
        )
        msg = _dict_to_normalized_message(d)
        assert msg.tool_call is not None
        assert msg.tool_call.id == "tc-1"
        assert msg.tool_call.name == "bash"
        assert msg.tool_call.input == {"cmd": "ls"}

    def test_with_tool_result(self):
        d = _sample_message_dict(
            tool_result={"call_id": "tc-1", "output": "ok", "status": "success"}
        )
        msg = _dict_to_normalized_message(d)
        assert msg.tool_result is not None
        assert msg.tool_result.call_id == "tc-1"
        assert msg.tool_result.status == "success"

    def test_minimal_fields(self):
        d = {
            "id": "msg-min",
            "session_id": "sess-min",
            "source": "gemini_cli",
            "msg_type": "user",
        }
        msg = _dict_to_normalized_message(d)
        assert msg.id == "msg-min"
        assert msg.content is None
        assert msg.tokens.input == 0

    def test_null_tokens(self):
        d = _sample_message_dict(tokens=None)
        msg = _dict_to_normalized_message(d)
        assert msg.tokens.input == 0


class TestValidateMessageDict:
    def test_valid(self):
        assert _validate_message_dict(_sample_message_dict()) is None

    def test_missing_id(self):
        d = _sample_message_dict()
        del d["id"]
        err = _validate_message_dict(d)
        assert err is not None
        assert "id" in err

    def test_missing_multiple(self):
        err = _validate_message_dict({})
        assert err is not None
        assert "id" in err
        assert "session_id" in err


# ── Integration: HTTP server test ─────────────────────────────────────


class TestHTTPIntegration:
    """Spin up a real HTTP server and test with http.client."""

    def _start_server(self, accumulator):
        loop = asyncio.new_event_loop()
        mock_conn = AsyncMock()
        mock_result = AsyncMock()
        mock_result.fetchone = AsyncMock(return_value=(1,))
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_conn.commit = AsyncMock()
        pool = _mock_pool(mock_conn)

        def _run_loop():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        loop_thread = threading.Thread(target=_run_loop, daemon=True)
        loop_thread.start()

        server = create_server(pool, accumulator, loop, "127.0.0.1", 0)
        port = server.server_address[1]
        return server, loop, loop_thread, port

    def test_health_endpoint(self):
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        accumulator = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        server, loop, loop_thread, port = self._start_server(accumulator)

        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/health")
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["status"] == "ok"
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            asyncio.run_coroutine_threadsafe(accumulator.close(), loop).result(timeout=5)
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=5)
            loop.close()

    def test_ingest_endpoint(self):
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        accumulator = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        server, loop, loop_thread, port = self._start_server(accumulator)

        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            body = json.dumps([_sample_message_dict()])
            conn.request(
                "POST", "/ingest", body=body,
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read())
            assert data["ingested"] == 1
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            asyncio.run_coroutine_threadsafe(accumulator.close(), loop).result(timeout=5)
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=5)
            loop.close()

    def test_not_found(self):
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        accumulator = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        server, loop, loop_thread, port = self._start_server(accumulator)

        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/nonexistent")
            resp = conn.getresponse()
            assert resp.status == 404
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            asyncio.run_coroutine_threadsafe(accumulator.close(), loop).result(timeout=5)
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=5)
            loop.close()


# ── Dashboard handler tests (H4) ────────────────────────────────────


class TestParseQs:
    def test_parses_query_string(self):
        result = _parse_qs("/api/sessions?source=claude_code&limit=10")
        assert result["source"] == "claude_code"
        assert result["limit"] == "10"

    def test_empty_query_string(self):
        result = _parse_qs("/api/sessions")
        assert result == {}

    def test_path_without_query(self):
        result = _parse_qs("/api/feed")
        assert result == {}


class TestSerializeRow:
    def test_serializes_plain_dict(self):
        row = {"id": "sess-1", "count": 42}
        result = _serialize_row(row)
        assert result == {"id": "sess-1", "count": 42}

    def test_serializes_datetime(self):
        row = {"id": "sess-1", "created_at": datetime(2026, 2, 6, 10, 0)}
        result = _serialize_row(row)
        assert result["created_at"] == "2026-02-06T10:00:00"

    def test_passes_through_none(self):
        row = {"id": "sess-1", "optional": None}
        result = _serialize_row(row)
        assert result["optional"] is None


class TestHandleApiStats:
    async def test_returns_stats(self):
        total_sessions = {"n": 5}
        total_messages = {"n": 100}
        by_source = [{"source": "claude_code", "count": 80}]
        by_type = [{"msg_type": "assistant", "count": 50}]
        tokens = {"input": 1000, "output": 500, "cached": 200, "thinking": 100}
        by_org = [{"org": "test-org", "session_count": 5, "message_count": 100}]

        mock_conn = _mock_conn_with_cursor_multi(
            [total_sessions, total_messages, by_source, by_type, tokens, by_org]
        )
        pool = _mock_pool(mock_conn)

        resp_body, status = await handle_api_stats(pool, "/api/stats")
        resp = json.loads(resp_body)
        assert status == 200
        assert resp["total_sessions"] == 5
        assert resp["total_messages"] == 100

    async def test_handles_db_error(self):
        pool = _mock_pool(error=Exception("DB down"))
        resp_body, status = await handle_api_stats(pool, "/api/stats")
        assert status == 500


class TestHandleApiSessions:
    async def test_returns_sessions(self):
        mock_conn = _mock_conn_with_cursor(fetchall_return=[
            {"id": "sess-1", "source": "claude_code", "message_count": 10},
        ])
        pool = _mock_pool(mock_conn)

        resp_body, status = await handle_api_sessions(pool, "/api/sessions")
        resp = json.loads(resp_body)
        assert status == 200
        assert len(resp) == 1
        assert resp[0]["id"] == "sess-1"

    async def test_handles_source_filter(self):
        mock_conn = _mock_conn_with_cursor(fetchall_return=[])
        pool = _mock_pool(mock_conn)

        resp_body, status = await handle_api_sessions(pool, "/api/sessions?source=claude_code")
        assert status == 200

    async def test_handles_date_filter(self):
        mock_conn = _mock_conn_with_cursor(fetchall_return=[])
        pool = _mock_pool(mock_conn)

        resp_body, status = await handle_api_sessions(pool, "/api/sessions?date=2026-04-16")
        assert status == 200
        # Verify get_sessions was called with date parameter
        call_args = mock_conn._cur.execute.call_args
        assert "2026-04-16" in call_args[0][1]

    async def test_handles_db_error(self):
        pool = _mock_pool(error=Exception("DB down"))
        resp_body, status = await handle_api_sessions(pool, "/api/sessions")
        assert status == 500


class TestHandleApiMessages:
    async def test_returns_messages(self):
        mock_conn = _mock_conn_with_cursor(fetchall_return=[
            {"id": "msg-1", "session_id": "sess-1", "msg_type": "user", "content": "hello"},
        ])
        pool = _mock_pool(mock_conn)

        resp_body, status = await handle_api_messages(pool, "/api/messages?session_id=sess-1")
        resp = json.loads(resp_body)
        assert status == 200
        assert len(resp) == 1

    async def test_requires_session_id(self):
        pool = MagicMock()
        resp_body, status = await handle_api_messages(pool, "/api/messages")
        resp = json.loads(resp_body)
        assert status == 400
        assert "session_id" in resp["error"]

    async def test_handles_db_error(self):
        pool = _mock_pool(error=Exception("DB down"))
        resp_body, status = await handle_api_messages(pool, "/api/messages?session_id=x")
        assert status == 500


class TestHandleApiFeed:
    async def test_returns_feed(self):
        mock_conn = _mock_conn_with_cursor(fetchall_return=[
            {"id": "msg-1", "session_id": "sess-1", "msg_type": "user", "content_preview": "hi"},
        ])
        pool = _mock_pool(mock_conn)

        resp_body, status = await handle_api_feed(pool, "/api/feed")
        resp = json.loads(resp_body)
        assert status == 200
        assert len(resp) == 1

    async def test_feed_with_since(self):
        mock_conn = _mock_conn_with_cursor(fetchall_return=[])
        pool = _mock_pool(mock_conn)

        resp_body, status = await handle_api_feed(pool, "/api/feed?since=2026-02-06T10:00:00Z")
        assert status == 200

    async def test_handles_db_error(self):
        pool = _mock_pool(error=Exception("DB down"))
        resp_body, status = await handle_api_feed(pool, "/api/feed")
        assert status == 500


# ── Role-based auth integration tests ─────────────────────────────────


class TestRoleBasedAuth:
    """HTTP integration tests for role-based auth."""

    def _start_server_with_keys(self, accumulator, admin_keys=None, push_keys=None):
        loop = asyncio.new_event_loop()
        mock_conn = AsyncMock()
        mock_result = AsyncMock()
        mock_result.fetchone = AsyncMock(return_value=(1,))
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_conn.commit = AsyncMock()

        # For cursor-based queries (stats, sessions, etc.)
        cur = AsyncMock()
        cur_result = AsyncMock()
        cur_result.fetchall = AsyncMock(return_value=[])
        cur_result.fetchone = AsyncMock(return_value={"n": 0})
        cur.execute = AsyncMock(return_value=cur_result)
        mock_conn.cursor = lambda **kwargs: _async_cm(cur)

        pool = _mock_pool(mock_conn)

        def _run_loop():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        loop_thread = threading.Thread(target=_run_loop, daemon=True)
        loop_thread.start()

        server = create_server(
            pool, accumulator, loop, "127.0.0.1", 0,
            admin_keys=admin_keys or set(),
            push_keys=push_keys or set(),
        )
        port = server.server_address[1]
        return server, loop, loop_thread, port

    def _cleanup(self, server, loop, loop_thread, accumulator, thread):
        server.shutdown()
        thread.join(timeout=5)
        asyncio.run_coroutine_threadsafe(accumulator.close(), loop).result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        loop.close()

    def test_push_key_can_ingest(self):
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        accumulator = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        server, loop, loop_thread, port = self._start_server_with_keys(
            accumulator, push_keys={"push_test123"},
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            body = json.dumps([_sample_message_dict()])
            conn.request(
                "POST", "/ingest", body=body,
                headers={"Content-Type": "application/json", "X-API-Key": "push_test123"},
            )
            resp = conn.getresponse()
            assert resp.status == 200
            conn.close()
        finally:
            self._cleanup(server, loop, loop_thread, accumulator, thread)

    def test_push_key_cannot_read_sessions(self):
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        accumulator = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        server, loop, loop_thread, port = self._start_server_with_keys(
            accumulator, push_keys={"push_test123"},
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request(
                "GET", "/api/sessions",
                headers={"X-API-Key": "push_test123"},
            )
            resp = conn.getresponse()
            assert resp.status == 401
            conn.close()
        finally:
            self._cleanup(server, loop, loop_thread, accumulator, thread)

    def test_admin_key_can_read_sessions(self):
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        accumulator = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        server, loop, loop_thread, port = self._start_server_with_keys(
            accumulator, admin_keys={"admin_test123"},
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request(
                "GET", "/api/sessions",
                headers={"X-API-Key": "admin_test123"},
            )
            resp = conn.getresponse()
            assert resp.status == 200
            conn.close()
        finally:
            self._cleanup(server, loop, loop_thread, accumulator, thread)

    def test_no_key_rejected_when_auth_enabled(self):
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        accumulator = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        server, loop, loop_thread, port = self._start_server_with_keys(
            accumulator, admin_keys={"admin_test123"}, push_keys={"push_test123"},
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            # POST without key
            body = json.dumps([_sample_message_dict()])
            conn.request("POST", "/ingest", body=body,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            assert resp.status == 401
            resp.read()  # consume body before next request
            conn.close()

            # GET without key
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/sessions")
            resp = conn.getresponse()
            assert resp.status == 401
            conn.close()
        finally:
            self._cleanup(server, loop, loop_thread, accumulator, thread)

    def test_health_is_public(self):
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        accumulator = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        server, loop, loop_thread, port = self._start_server_with_keys(
            accumulator, admin_keys={"admin_test123"},
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/health")
            resp = conn.getresponse()
            assert resp.status == 200
            conn.close()
        finally:
            self._cleanup(server, loop, loop_thread, accumulator, thread)

    def test_no_auth_when_no_keys_configured(self):
        """When no keys are set, all endpoints are accessible (backwards compat)."""
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        accumulator = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        server, loop, loop_thread, port = self._start_server_with_keys(accumulator)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            body = json.dumps([_sample_message_dict()])
            conn.request("POST", "/ingest", body=body,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            assert resp.status == 200
            conn.close()
        finally:
            self._cleanup(server, loop, loop_thread, accumulator, thread)


# ── BatchAccumulator.stats tests ───────────────────────────────────


class TestBatchAccumulatorStats:
    async def test_stats_initial_state(self):
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        acc = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        try:
            stats = acc.stats
            assert stats["batch_accumulator"]["pending"] == 0
            assert stats["batch_accumulator"]["total_flushed"] == 0
            assert stats["batch_accumulator"]["total_dropped"] == 0
            assert stats["batch_accumulator"]["flush_failures"] == 0
            assert stats["recent_ingestion"]["messages_last_1m"] == 0
            assert stats["recent_ingestion"]["messages_last_5m"] == 0
            assert stats["recent_ingestion"]["last_flush_at"] is None
            assert stats["recent_ingestion"]["idle_seconds"] is None
        finally:
            await acc.close()

    async def test_stats_after_flush(self):
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        acc = BatchAccumulator(flush_callback=flush_mock, batch_size=5)
        try:
            msgs = [_sample_normalized_message(id=f"msg-{i}") for i in range(5)]
            await acc.add(msgs)
            stats = acc.stats
            assert stats["batch_accumulator"]["pending"] == 0
            assert stats["batch_accumulator"]["total_flushed"] == 5
            assert stats["recent_ingestion"]["messages_last_1m"] == 5
            assert stats["recent_ingestion"]["messages_last_5m"] == 5
            assert stats["recent_ingestion"]["last_flush_at"] is not None
            assert stats["recent_ingestion"]["idle_seconds"] is not None
            assert stats["recent_ingestion"]["idle_seconds"] < 2.0
        finally:
            await acc.close()

    async def test_stats_with_pending_messages(self):
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        acc = BatchAccumulator(flush_callback=flush_mock, batch_size=100)
        try:
            msgs = [_sample_normalized_message(id=f"msg-{i}") for i in range(3)]
            await acc.add(msgs)
            stats = acc.stats
            assert stats["batch_accumulator"]["pending"] == 3
            assert stats["batch_accumulator"]["total_flushed"] == 0
        finally:
            await acc.close()


# ── Monitor handler tests ──────────────────────────────────────────


class TestHandleApiMonitor:
    async def test_idle_status(self):
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        acc = BatchAccumulator(flush_callback=flush_mock, batch_size=100)

        total_sessions = {"n": 10}
        total_messages = {"n": 50}
        by_source = []
        by_type = []
        tokens = {"input": 0, "output": 0, "cached": 0, "thinking": 0}
        by_org = []
        mock_conn = _mock_conn_with_cursor_multi(
            [total_sessions, total_messages, by_source, by_type, tokens, by_org]
        )
        pool = _mock_pool(mock_conn)

        try:
            resp_body, status = await handle_api_monitor(pool, acc)
            resp = json.loads(resp_body)
            assert status == 200
            assert resp["status"] == "idle"
            assert resp["database"]["total_sessions"] == 10
            assert resp["database"]["total_messages"] == 50
            assert "batch_accumulator" in resp
            assert "recent_ingestion" in resp
        finally:
            await acc.close()

    async def test_receiving_status(self):
        flush_mock = AsyncMock(side_effect=lambda msgs: len(msgs))
        acc = BatchAccumulator(flush_callback=flush_mock, batch_size=5)

        # Flush some messages first to get "receiving" status
        msgs = [_sample_normalized_message(id=f"msg-{i}") for i in range(5)]
        await acc.add(msgs)

        total_sessions = {"n": 10}
        total_messages = {"n": 50}
        mock_conn = _mock_conn_with_cursor_multi(
            [total_sessions, total_messages, [], [], {"input": 0, "output": 0, "cached": 0, "thinking": 0}, []]
        )
        pool = _mock_pool(mock_conn)

        try:
            resp_body, status = await handle_api_monitor(pool, acc)
            resp = json.loads(resp_body)
            assert status == 200
            assert resp["status"] == "receiving"
        finally:
            await acc.close()


# ── Bulk file progress handler tests ───────────────────────────────


class TestHandleFileProgressBulk:
    async def test_valid_bulk_upsert(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        pool = _mock_pool(mock_conn)

        body = json.dumps([
            {"raw_file_path": "/tmp/a.jsonl", "source": "claude_code", "last_line_read": 100},
            {"raw_file_path": "/tmp/b.jsonl", "source": "claude_code", "last_line_read": 200},
        ]).encode()
        resp_body, status = await handle_file_progress_bulk(body, pool)
        resp = json.loads(resp_body)
        assert status == 200
        assert resp["ok"] is True
        assert resp["updated"] == 2
        assert mock_conn.execute.call_count == 2

    async def test_empty_array(self):
        pool = MagicMock()
        body = json.dumps([]).encode()
        resp_body, status = await handle_file_progress_bulk(body, pool)
        resp = json.loads(resp_body)
        assert status == 200
        assert resp["updated"] == 0

    async def test_invalid_json(self):
        pool = MagicMock()
        resp_body, status = await handle_file_progress_bulk(b"bad json", pool)
        assert status == 400

    async def test_not_an_array(self):
        pool = MagicMock()
        body = json.dumps({"raw_file_path": "/tmp/a.jsonl"}).encode()
        resp_body, status = await handle_file_progress_bulk(body, pool)
        assert status == 400

    async def test_missing_fields(self):
        pool = MagicMock()
        body = json.dumps([{"raw_file_path": "/tmp/a.jsonl"}]).encode()
        resp_body, status = await handle_file_progress_bulk(body, pool)
        resp = json.loads(resp_body)
        assert status == 400
        assert "missing fields" in resp["error"]

    async def test_handles_db_error(self):
        pool = _mock_pool(error=Exception("DB down"))
        body = json.dumps([
            {"raw_file_path": "/tmp/a.jsonl", "source": "claude_code", "last_line_read": 100},
        ]).encode()
        resp_body, status = await handle_file_progress_bulk(body, pool)
        assert status == 500
