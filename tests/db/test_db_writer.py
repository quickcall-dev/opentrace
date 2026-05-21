# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for opentrace.db.writer — batch COPY writer for NormalizedMessage.

These tests require a running PostgreSQL instance. They are skipped
automatically if psycopg is not installed or the database is unreachable.

Run with: pytest tests/test_db_writer.py -v
Requires: scripts/dev-db.sh start
"""


import json
import os
import uuid
from typing import AsyncIterator

import pytest

# Skip entire module if psycopg is not installed
psycopg = pytest.importorskip("psycopg")

from psycopg import AsyncConnection  # noqa: E402

from opentrace.db.migrations import ensure_schema  # noqa: E402
from opentrace.db.writer import BatchWriter  # noqa: E402
from opentrace.schemas.unified import (  # noqa: E402
    NormalizedMessage,
    TokenUsage,
    ToolCall,
    ToolResult,
)

DSN = os.environ.get(
    "QUICKCALL_OPENTRACE_DSN", "postgresql://opentrace:opentrace_dev@localhost:5432/opentrace"
)


def _can_connect() -> bool:
    """Check if the test database is reachable."""
    try:
        with psycopg.connect(DSN, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _can_connect(),
    reason="PostgreSQL not available (run scripts/dev-db.sh start)",
)


def _make_message(
    msg_type: str = "assistant",
    session_id: str | None = None,
    content: str = "Hello world",
    tokens: TokenUsage | None = None,
    tool_call: ToolCall | None = None,
    tool_result: ToolResult | None = None,
    model: str = "test-model",
) -> NormalizedMessage:
    return NormalizedMessage(
        id=str(uuid.uuid4()),
        session_id=session_id or str(uuid.uuid4()),
        source="claude_code",
        source_schema_version=1,
        msg_type=msg_type,
        timestamp="2026-02-06T10:00:00Z",
        content=content,
        tokens=tokens or TokenUsage(),
        tool_call=tool_call,
        tool_result=tool_result,
        model=model,
    )


@requires_db
class TestBatchWriter:
    """Integration tests for BatchWriter against a real PostgreSQL instance."""

    @pytest.fixture(autouse=True)
    async def _setup_db(self) -> AsyncIterator[None]:
        """Ensure schema exists and clean up test data after each test."""
        self.conn = await AsyncConnection.connect(DSN)
        await ensure_schema(self.conn)
        yield
        # Clean up all test data
        await self.conn.execute("DELETE FROM tool_results")
        await self.conn.execute("DELETE FROM tool_calls")
        await self.conn.execute("DELETE FROM token_usage")
        await self.conn.execute("DELETE FROM messages")
        await self.conn.execute("DELETE FROM sessions")
        await self.conn.commit()
        await self.conn.close()

    async def test_write_empty_batch(self) -> None:
        writer = BatchWriter(self.conn)
        count = await writer.write([])
        assert count == 0

    async def test_write_single_message(self) -> None:
        msg = _make_message()
        writer = BatchWriter(self.conn)
        count = await writer.write([msg])
        assert count == 1

        result = await self.conn.execute(
            "SELECT id, content, msg_type FROM messages WHERE id = %s",
            (msg.id,),
        )
        row = await result.fetchone()
        assert row is not None
        assert row[0] == msg.id
        assert row[1] == "Hello world"
        assert row[2] == "assistant"

    async def test_write_creates_session(self) -> None:
        session_id = str(uuid.uuid4())
        msg = _make_message(session_id=session_id)
        writer = BatchWriter(self.conn)
        await writer.write([msg])

        result = await self.conn.execute(
            "SELECT id, source, model FROM sessions WHERE id = %s",
            (session_id,),
        )
        row = await result.fetchone()
        assert row is not None
        assert row[0] == session_id
        assert row[1] == "claude_code"
        assert row[2] == "test-model"

    async def test_write_with_token_usage(self) -> None:
        tokens = TokenUsage(input=100, output=50, cached=10, thinking=5)
        msg = _make_message(tokens=tokens)
        writer = BatchWriter(self.conn)
        await writer.write([msg])

        result = await self.conn.execute(
            "SELECT input_tokens, output_tokens, cached_tokens, thinking_tokens "
            "FROM token_usage WHERE message_id = %s",
            (msg.id,),
        )
        row = await result.fetchone()
        assert row is not None
        assert row == (100, 50, 10, 5)

    async def test_write_with_tool_call(self) -> None:
        tc = ToolCall(id="tc-1", name="read_file", input={"path": "/tmp/test"})
        msg = _make_message(msg_type="tool_call", tool_call=tc)
        writer = BatchWriter(self.conn)
        await writer.write([msg])

        result = await self.conn.execute(
            "SELECT tool_id, tool_name, tool_input "
            "FROM tool_calls WHERE message_id = %s",
            (msg.id,),
        )
        row = await result.fetchone()
        assert row is not None
        assert row[0] == "tc-1"
        assert row[1] == "read_file"
        tool_input = row[2] if isinstance(row[2], dict) else json.loads(row[2])
        assert tool_input == {"path": "/tmp/test"}

    async def test_write_with_tool_result(self) -> None:
        tr = ToolResult(call_id="tc-1", output="file contents", status="success")
        msg = _make_message(msg_type="tool_result", tool_result=tr)
        writer = BatchWriter(self.conn)
        await writer.write([msg])

        result = await self.conn.execute(
            "SELECT call_id, output, status "
            "FROM tool_results WHERE message_id = %s",
            (msg.id,),
        )
        row = await result.fetchone()
        assert row is not None
        assert row == ("tc-1", "file contents", "success")

    async def test_write_multiple_messages_same_session(self) -> None:
        session_id = str(uuid.uuid4())
        messages = [
            _make_message(session_id=session_id, msg_type="user", content="hi"),
            _make_message(session_id=session_id, msg_type="assistant", content="hello"),
        ]
        writer = BatchWriter(self.conn)
        count = await writer.write(messages)
        assert count == 2

        result = await self.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = %s",
            (session_id,),
        )
        row = await result.fetchone()
        assert row[0] == 2

        # Only one session should be created
        result = await self.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE id = %s",
            (session_id,),
        )
        row = await result.fetchone()
        assert row[0] == 1

    async def test_write_skips_zero_token_usage(self) -> None:
        msg = _make_message(tokens=TokenUsage())
        writer = BatchWriter(self.conn)
        await writer.write([msg])

        result = await self.conn.execute(
            "SELECT COUNT(*) FROM token_usage WHERE message_id = %s",
            (msg.id,),
        )
        row = await result.fetchone()
        assert row[0] == 0

    async def test_session_upsert_updates_last_updated(self) -> None:
        session_id = str(uuid.uuid4())
        msg1 = _make_message(session_id=session_id, model="model-v1")
        msg2 = _make_message(session_id=session_id, model="model-v2")

        writer = BatchWriter(self.conn)
        await writer.write([msg1])
        await writer.write([msg2])

        result = await self.conn.execute(
            "SELECT model FROM sessions WHERE id = %s",
            (session_id,),
        )
        row = await result.fetchone()
        assert row is not None
        # Upsert should update model
        assert row[0] == "model-v2"

    async def test_duplicate_message_ids_in_batch(self) -> None:
        """Duplicate IDs in a single batch must not raise CardinalityViolation.

        The batch accumulator can collect the same message ID from multiple
        ingest requests. ON CONFLICT DO UPDATE crashes if the same row is
        affected twice in one INSERT — staging tables must be deduped first.
        """
        msg_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        msg1 = NormalizedMessage(
            id=msg_id, session_id=session_id, source="claude_code",
            source_schema_version=1, msg_type="assistant",
            timestamp="2026-02-20T00:00:00Z", content="first version",
            tokens=TokenUsage(input=100, output=50),
            tool_call=ToolCall(id="tc-dup", name="read_file", input={"v": 1}),
        )
        msg2 = NormalizedMessage(
            id=msg_id, session_id=session_id, source="claude_code",
            source_schema_version=1, msg_type="assistant",
            timestamp="2026-02-20T00:00:00Z", content="second version",
            tokens=TokenUsage(input=200, output=100),
            tool_call=ToolCall(id="tc-dup", name="read_file", input={"v": 2}),
        )

        writer = BatchWriter(self.conn)
        # This raised CardinalityViolation before the dedup fix
        count = await writer.write([msg1, msg2])
        assert count == 1

        # Verify message stored (last wins)
        row = await (await self.conn.execute(
            "SELECT content FROM messages WHERE id = %s", (msg_id,)
        )).fetchone()
        assert row is not None
        assert row[0] == "second version"

        # Verify token_usage deduped
        row = await (await self.conn.execute(
            "SELECT input_tokens FROM token_usage WHERE message_id = %s", (msg_id,)
        )).fetchone()
        assert row is not None
        assert row[0] == 200

        # Verify tool_calls deduped
        row = await (await self.conn.execute(
            "SELECT tool_input FROM tool_calls WHERE message_id = %s", (msg_id,)
        )).fetchone()
        assert row is not None
        tool_input = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        assert tool_input == {"v": 2}

    async def test_duplicate_tool_result_ids_in_batch(self) -> None:
        """Duplicate tool_result message IDs must not crash."""
        msg_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        msg1 = NormalizedMessage(
            id=msg_id, session_id=session_id, source="claude_code",
            source_schema_version=1, msg_type="tool_result",
            timestamp="2026-02-20T00:00:00Z",
            tool_result=ToolResult(call_id="tc-1", output="old output", status="failure"),
        )
        msg2 = NormalizedMessage(
            id=msg_id, session_id=session_id, source="claude_code",
            source_schema_version=1, msg_type="tool_result",
            timestamp="2026-02-20T00:00:00Z",
            tool_result=ToolResult(call_id="tc-1", output="new output", status="success"),
        )

        writer = BatchWriter(self.conn)
        count = await writer.write([msg1, msg2])
        assert count == 1

        row = await (await self.conn.execute(
            "SELECT output, status FROM tool_results WHERE message_id = %s", (msg_id,)
        )).fetchone()
        assert row is not None
        assert row[0] == "new output"
        assert row[1] == "success"
