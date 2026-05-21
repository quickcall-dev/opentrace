# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for Cursor IDE schema transformations."""

import os
from pathlib import Path

import pytest

from opentrace.schemas.cursor.transform import (
    extract_session_id,
    transform_cursor_v1,
    transform_composer_metadata,
    transform_tool_invocation,
)
from opentrace.schemas.unified import NormalizedMessage
from opentrace.utils.cursor_parser import parse_agent_transcript


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestExtractSessionId:
    """Tests for extract_session_id function."""

    def test_extracts_composer_id_from_path(self):
        """Test extraction of composerId from transcript path."""
        path = "~/.cursor/projects/-Users-bob-myproject/agent-transcripts/abc123-def456.txt"
        result = extract_session_id(path)
        assert result == "abc123-def456"

    def test_handles_complex_uuid(self):
        """Test extraction of full UUID."""
        path = "/home/user/.cursor/projects/proj/agent-transcripts/550e8400-e29b-41d4-a716-446655440000.txt"
        result = extract_session_id(path)
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_returns_path_if_no_match(self):
        """Test fallback when pattern doesn't match."""
        path = "/some/other/path"
        result = extract_session_id(path)
        assert result == path


class TestCursorTransform:
    """Tests for Cursor transcript transformation."""

    @pytest.fixture
    def sample_transcript(self):
        """Load and parse sample Cursor transcript."""
        transcript_path = FIXTURES_DIR / "cursor_transcript_sample.txt"
        return parse_agent_transcript(str(transcript_path))

    def test_transforms_user_message(self, sample_transcript):
        """Test transformation of user message."""
        result = transform_cursor_v1(sample_transcript, str(FIXTURES_DIR / "cursor_transcript_sample.txt"))

        # First message should be user
        user_msgs = [m for m in result if m.msg_type == "user"]
        assert len(user_msgs) >= 1

        first_user = user_msgs[0]
        assert first_user.msg_type == "user"
        assert "fibonacci" in first_user.content.lower()
        assert first_user.source == "cursor"
        assert first_user.source_schema_version == 1

    def test_transforms_assistant_message(self, sample_transcript):
        """Test transformation of assistant message."""
        result = transform_cursor_v1(sample_transcript, str(FIXTURES_DIR / "cursor_transcript_sample.txt"))

        # Should have assistant messages
        assistant_msgs = [m for m in result if m.msg_type == "assistant"]
        assert len(assistant_msgs) >= 1

        first_assistant = assistant_msgs[0]
        assert first_assistant.msg_type == "assistant"
        assert first_assistant.source == "cursor"

    def test_extracts_thinking_block(self, sample_transcript):
        """Test that thinking blocks are extracted."""
        result = transform_cursor_v1(sample_transcript, str(FIXTURES_DIR / "cursor_transcript_sample.txt"))

        # Find assistant messages with thinking
        msgs_with_thinking = [m for m in result if m.thinking]
        assert len(msgs_with_thinking) >= 1

        # Verify thinking content
        first_thinking = msgs_with_thinking[0]
        assert "fibonacci" in first_thinking.thinking.lower() or "iterative" in first_thinking.thinking.lower()

    def test_transforms_tool_call(self, sample_transcript):
        """Test transformation of tool calls."""
        result = transform_cursor_v1(sample_transcript, str(FIXTURES_DIR / "cursor_transcript_sample.txt"))

        # Should have tool_call messages
        tool_calls = [m for m in result if m.msg_type == "tool_call"]
        assert len(tool_calls) >= 1

        first_call = tool_calls[0]
        assert first_call.tool_call is not None
        assert first_call.tool_call.name == "Write"
        assert "path" in first_call.tool_call.input

    def test_transforms_tool_result(self, sample_transcript):
        """Test transformation of tool results."""
        result = transform_cursor_v1(sample_transcript, str(FIXTURES_DIR / "cursor_transcript_sample.txt"))

        # Should have tool_result messages
        tool_results = [m for m in result if m.msg_type == "tool_result"]
        assert len(tool_results) >= 1

        first_result = tool_results[0]
        assert first_result.tool_result is not None
        assert first_result.tool_result.status == "success"

    def test_handles_empty_transcript(self):
        """Test handling of empty transcript."""
        empty_transcript = {
            "composer_id": "empty-test",
            "file_path": "/test/empty.txt",
            "messages": [],
        }
        result = transform_cursor_v1(empty_transcript, "/test/empty.txt")
        assert result == []

    def test_preserves_session_id(self, sample_transcript):
        """Test that session_id is preserved across messages."""
        result = transform_cursor_v1(sample_transcript, str(FIXTURES_DIR / "cursor_transcript_sample.txt"))

        session_ids = set(m.session_id for m in result)
        assert len(session_ids) == 1  # All messages have same session_id

    def test_message_ordering(self, sample_transcript):
        """Test that messages are in correct order."""
        result = transform_cursor_v1(sample_transcript, str(FIXTURES_DIR / "cursor_transcript_sample.txt"))

        # First message should be user
        assert result[0].msg_type == "user"

        # User messages and assistant messages should alternate (roughly)
        user_indices = [i for i, m in enumerate(result) if m.msg_type == "user"]
        assert user_indices[0] < user_indices[1] if len(user_indices) > 1 else True


class TestTransformToolInvocation:
    """Tests for transform_tool_invocation function."""

    def test_transforms_tool_call(self):
        """Test transformation of a tool call."""
        tool = {
            "type": "tool_call",
            "tool_name": "Read",
            "parameters": {"path": "/test/file.py"},
            "result": None,
        }

        result = transform_tool_invocation(tool, "session-1", "/test.txt", 0)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "tool_call"
        assert msg.tool_call.name == "Read"
        assert msg.tool_call.input == {"path": "/test/file.py"}

    def test_transforms_tool_result(self):
        """Test transformation of a tool result."""
        tool = {
            "type": "tool_result",
            "tool_name": "Read",
            "parameters": {},
            "result": "file contents here",
        }

        result = transform_tool_invocation(tool, "session-1", "/test.txt", 0)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "tool_result"
        assert msg.tool_result.output == "file contents here"
        assert msg.tool_result.status == "success"

    def test_handles_empty_result(self):
        """Test handling of empty tool result."""
        tool = {
            "type": "tool_result",
            "tool_name": "Write",
            "parameters": {},
            "result": None,
        }

        result = transform_tool_invocation(tool, "session-1", "/test.txt", 0)

        assert len(result) == 1
        msg = result[0]
        assert msg.tool_result.output == ""


class TestTransformComposerMetadata:
    """Tests for transform_composer_metadata function."""

    def test_transforms_composer_entry(self):
        """Test transformation of composer metadata."""
        composer = {
            "composerId": "test-composer-123",
            "createdAt": 1707100000000,  # Unix timestamp in ms
            "unifiedMode": "agent",
            "name": "Test Session",
            "totalLinesAdded": 100,
            "totalLinesRemoved": 50,
        }

        result = transform_composer_metadata(composer, "/db/state.vscdb")

        assert result.msg_type == "system"
        assert result.session_id == "test-composer-123"
        assert result.source == "cursor"
        assert "agent" in result.content.lower()
        assert "Test Session" in result.content
        assert result.raw_data is not None
        assert result.raw_data["composerId"] == "test-composer-123"

    def test_handles_missing_fields(self):
        """Test handling of composer with missing optional fields."""
        composer = {
            "composerId": "minimal-123",
        }

        result = transform_composer_metadata(composer, "/db/state.vscdb")

        assert result.session_id == "minimal-123"
        assert result.msg_type == "system"

    def test_converts_timestamp(self):
        """Test timestamp conversion from Unix ms to ISO 8601."""
        composer = {
            "composerId": "ts-test",
            "createdAt": 1707100000000,  # 2024-02-05T04:26:40Z
        }

        result = transform_composer_metadata(composer, "/db/state.vscdb")

        assert result.timestamp != ""
        assert "2024" in result.timestamp or "T" in result.timestamp  # ISO format


class TestCursorRealSession:
    """Integration tests with real Cursor data (skipped in CI)."""

    def test_can_parse_and_transform_real_transcript(self):
        """Test parsing and transforming a real Cursor transcript."""

        cursor_projects = Path(os.path.expanduser("~/.cursor/projects"))

        if not cursor_projects.exists():
            pytest.skip("Cursor projects directory not found")

        # Find any transcript file
        transcripts = list(cursor_projects.glob("*/agent-transcripts/*.txt"))
        if not transcripts:
            pytest.skip("No Cursor transcripts found")

        transcript_path = transcripts[0]
        transcript = parse_agent_transcript(str(transcript_path))
        messages = transform_cursor_v1(transcript, str(transcript_path))

        # Should have parsed some messages
        assert len(messages) > 0

        # Verify message structure
        for msg in messages:
            assert isinstance(msg, NormalizedMessage)
            assert msg.source == "cursor"
            assert msg.source_schema_version == 1
            assert msg.session_id

        # Should have different message types
        msg_types = set(m.msg_type for m in messages)
        assert "user" in msg_types or "assistant" in msg_types
