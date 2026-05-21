# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for schema transformations."""

import json
import os
from pathlib import Path

import pytest

from opentrace.schemas.claude_code.transform import transform_claude_v1
from opentrace.schemas.codex_cli.transform import CodexTransformContext, transform_codex_v1
from opentrace.schemas.gemini_cli.transform import transform_gemini_v1
from opentrace.schemas.unified import (
    NormalizedMessage,
    HookInfo,
    ProgressData,
    QueueOperationData,
    SystemEventData,
)


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestClaudeCodeTransform:
    """Tests for Claude Code v1 transformation."""

    @pytest.fixture
    def sample_lines(self) -> list[dict]:
        """Load sample Claude Code JSONL lines."""
        lines = []
        with open(FIXTURES_DIR / "claude_v1_sample.jsonl") as f:
            for line in f:
                if line.strip():
                    lines.append(json.loads(line))
        return lines

    def test_transforms_user_message(self, sample_lines):
        """Test transformation of user message."""
        user_line = sample_lines[0]
        result = transform_claude_v1(user_line, "/test/session.jsonl", 1)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "user"
        assert msg.content == "Build a blog app with Flask"
        assert msg.source == "claude_code"
        assert msg.source_schema_version == 1
        assert msg.id == "user-msg-001"

    def test_transforms_assistant_with_tool_use(self, sample_lines):
        """Test transformation of assistant message with tool use."""
        assistant_line = sample_lines[1]
        result = transform_claude_v1(assistant_line, "/test/session.jsonl", 2)

        # Should produce assistant message + tool call
        assert len(result) == 2

        # First is the assistant message
        assistant_msg = result[0]
        assert assistant_msg.msg_type == "assistant"
        assert "Flask blog application" in assistant_msg.content
        assert assistant_msg.thinking is not None
        assert "project structure" in assistant_msg.thinking

        # Token usage
        assert assistant_msg.tokens.input == 1500
        assert assistant_msg.tokens.output == 200
        assert assistant_msg.tokens.cached == 1000

        # Second is the tool call
        tool_msg = result[1]
        assert tool_msg.msg_type == "tool_call"
        assert tool_msg.tool_call is not None
        assert tool_msg.tool_call.name == "Write"
        assert tool_msg.tool_call.id == "tool-001"

    def test_transforms_tool_result(self, sample_lines):
        """Test transformation of tool result."""
        tool_result_line = sample_lines[2]
        result = transform_claude_v1(tool_result_line, "/test/session.jsonl", 3)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "tool_result"
        assert msg.tool_result is not None
        assert msg.tool_result.call_id == "tool-001"
        assert msg.tool_result.output == "File written successfully"

    def test_captures_file_history_snapshot(self, sample_lines):
        """Test that file-history-snapshot is captured as file_snapshot type."""
        snapshot_line = sample_lines[3]
        result = transform_claude_v1(snapshot_line, "/test/session.jsonl", 4)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "file_snapshot"
        assert msg.raw_data is not None
        assert msg.raw_data["type"] == "file-history-snapshot"

    def test_transforms_progress_hook_message(self, sample_lines):
        """Test transformation of progress message with hook data."""
        progress_line = sample_lines[4]  # hook_progress
        result = transform_claude_v1(progress_line, "/test/session.jsonl", 5)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "progress"
        assert msg.progress_data is not None
        assert msg.progress_data.progress_type == "hook_progress"
        assert msg.progress_data.hook_info is not None
        assert msg.progress_data.hook_info.event == "PostToolUse"
        assert msg.progress_data.hook_info.name == "PostToolUse:Write"
        assert msg.progress_data.hook_info.tool_use_id == "tool-001"

    def test_transforms_progress_bash_message(self, sample_lines):
        """Test transformation of progress message with bash data."""
        progress_line = sample_lines[5]  # bash_progress
        result = transform_claude_v1(progress_line, "/test/session.jsonl", 6)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "progress"
        assert msg.progress_data is not None
        assert msg.progress_data.progress_type == "bash_progress"
        assert msg.progress_data.stdout == "Installing dependencies..."

    def test_transforms_system_stop_hook_summary(self, sample_lines):
        """Test transformation of system stop_hook_summary message."""
        system_line = sample_lines[6]  # stop_hook_summary
        result = transform_claude_v1(system_line, "/test/session.jsonl", 7)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "system_event"
        assert msg.system_event_data is not None
        assert msg.system_event_data.subtype == "stop_hook_summary"
        assert msg.system_event_data.hook_count == 1
        assert msg.system_event_data.hook_infos is not None
        assert len(msg.system_event_data.hook_infos) == 1

    def test_transforms_system_turn_duration(self, sample_lines):
        """Test transformation of system turn_duration message."""
        system_line = sample_lines[7]  # turn_duration
        result = transform_claude_v1(system_line, "/test/session.jsonl", 8)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "system_event"
        assert msg.system_event_data is not None
        assert msg.system_event_data.subtype == "turn_duration"
        assert msg.system_event_data.duration_ms == 5000

    def test_transforms_queue_operation_running(self, sample_lines):
        """Test transformation of queue operation with running status."""
        queue_line = sample_lines[9]  # running task
        result = transform_claude_v1(queue_line, "/test/session.jsonl", 10)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "queue_operation"
        assert msg.queue_operation_data is not None
        assert msg.queue_operation_data.operation == "enqueue"
        assert msg.queue_operation_data.task_id == "task-001"
        assert msg.queue_operation_data.status == "running"
        assert msg.queue_operation_data.summary == "Running Flask development server"

    def test_transforms_queue_operation_failed(self, sample_lines):
        """Test transformation of queue operation with failed status."""
        queue_line = sample_lines[10]  # failed task
        result = transform_claude_v1(queue_line, "/test/session.jsonl", 11)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "queue_operation"
        assert msg.queue_operation_data is not None
        assert msg.queue_operation_data.task_id == "task-002"
        assert msg.queue_operation_data.status == "failed"
        assert msg.queue_operation_data.output_file == "/tmp/tasks/task-002.output"

    def test_transforms_result_success(self, sample_lines):
        """Test transformation of result message (success)."""
        result_line = sample_lines[11]  # success result
        result = transform_claude_v1(result_line, "/test/session.jsonl", 12)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "tool_result"
        assert msg.tool_result is not None
        assert msg.tool_result.call_id == "tool-002"
        assert msg.tool_result.status == "success"
        assert "successfully" in msg.tool_result.output.lower()

    def test_transforms_result_error(self, sample_lines):
        """Test transformation of result message (error)."""
        result_line = sample_lines[12]  # error result
        result = transform_claude_v1(result_line, "/test/session.jsonl", 13)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "tool_result"
        assert msg.tool_result is not None
        assert msg.tool_result.call_id == "tool-003"
        assert msg.tool_result.status == "failure"
        assert "error" in msg.tool_result.output.lower()

    def test_transforms_summary(self, sample_lines):
        """Test transformation of summary message."""
        summary_line = sample_lines[13]  # summary
        result = transform_claude_v1(summary_line, "/test/session.jsonl", 14)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "summary"
        assert msg.content is not None
        assert "Flask blog app" in msg.content
        assert msg.raw_data is not None


class TestCodexCliTransform:
    """Tests for Codex CLI v1 transformation."""

    @pytest.fixture
    def sample_lines(self) -> list[dict]:
        """Load sample Codex CLI JSONL lines."""
        lines = []
        with open(FIXTURES_DIR / "codex_v1_sample.jsonl") as f:
            for line in f:
                if line.strip():
                    lines.append(json.loads(line))
        return lines

    def test_session_meta_updates_context(self, sample_lines):
        """Test that session_meta updates context."""
        context = CodexTransformContext()
        result = transform_codex_v1(sample_lines[0], "/test/session.jsonl", 1, context)

        assert len(result) == 0  # No message produced
        assert context.session_id == "test-session-codex-001"
        assert context.cli_version == "0.95.0"

    def test_transforms_developer_message(self, sample_lines):
        """Test transformation of developer (system) message."""
        context = CodexTransformContext()
        transform_codex_v1(sample_lines[0], "/test/session.jsonl", 1, context)
        result = transform_codex_v1(sample_lines[1], "/test/session.jsonl", 2, context)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "system"
        assert "System instructions" in msg.content

    def test_transforms_user_message(self, sample_lines):
        """Test transformation of user message."""
        context = CodexTransformContext()
        transform_codex_v1(sample_lines[0], "/test/session.jsonl", 1, context)
        result = transform_codex_v1(sample_lines[2], "/test/session.jsonl", 3, context)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "user"
        assert msg.content == "Build a blog app with Flask"
        assert msg.source == "codex_cli"

    def test_turn_context_updates_model(self, sample_lines):
        """Test that turn_context updates current model."""
        context = CodexTransformContext()
        transform_codex_v1(sample_lines[0], "/test/session.jsonl", 1, context)
        result = transform_codex_v1(sample_lines[3], "/test/session.jsonl", 4, context)

        assert len(result) == 0  # No message produced
        assert context.current_model == "gpt-5"

    def test_token_count_null_info_handled(self, sample_lines):
        """Test that token_count with null info is handled."""
        context = CodexTransformContext()
        transform_codex_v1(sample_lines[0], "/test/session.jsonl", 1, context)
        # Line 4 has null info
        result = transform_codex_v1(sample_lines[4], "/test/session.jsonl", 5, context)

        assert len(result) == 0  # No message produced
        # Token usage should remain at default (0)
        assert context.last_token_usage.input == 0

    def test_token_count_updates_context(self, sample_lines):
        """Test that token_count updates context."""
        context = CodexTransformContext()
        transform_codex_v1(sample_lines[0], "/test/session.jsonl", 1, context)
        # Line 5 has actual token info
        result = transform_codex_v1(sample_lines[5], "/test/session.jsonl", 6, context)

        assert len(result) == 0  # No message produced
        assert context.last_token_usage.input == 11214
        assert context.last_token_usage.cached == 9728

    def test_transforms_function_call(self, sample_lines):
        """Test transformation of function call."""
        context = CodexTransformContext()
        # Process preceding lines to set up context
        for i, line in enumerate(sample_lines[:7], 1):
            transform_codex_v1(line, "/test/session.jsonl", i, context)

        result = transform_codex_v1(sample_lines[7], "/test/session.jsonl", 8, context)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "tool_call"
        assert msg.tool_call is not None
        assert msg.tool_call.name == "shell"
        # Arguments are now a nested structure
        assert msg.tool_call.input["command"] == ["bash", "-lc", "mkdir src"]

    def test_transforms_function_call_output(self, sample_lines):
        """Test transformation of function call output."""
        context = CodexTransformContext()
        result = transform_codex_v1(sample_lines[8], "/test/session.jsonl", 9, context)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "tool_result"
        assert msg.tool_result is not None
        assert msg.tool_result.call_id == "call_test_001"
        assert msg.tool_result.status == "success"

    def test_transforms_agent_message(self, sample_lines):
        """Test transformation of agent message."""
        context = CodexTransformContext()
        context.current_model = "gpt-5"
        result = transform_codex_v1(sample_lines[9], "/test/session.jsonl", 10, context)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "assistant"
        assert "src directory" in msg.content
        assert msg.model == "gpt-5"

    def test_transforms_turn_aborted(self, sample_lines):
        """Test transformation of turn_aborted event."""
        context = CodexTransformContext()
        result = transform_codex_v1(sample_lines[10], "/test/session.jsonl", 11, context)

        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "info"
        assert "aborted" in msg.content.lower()
        assert "interrupted" in msg.content


class TestGeminiCliTransform:
    """Tests for Gemini CLI v1 transformation."""

    @pytest.fixture
    def sample_session(self) -> dict:
        """Load sample Gemini CLI session."""
        with open(FIXTURES_DIR / "gemini_v1_sample.json") as f:
            return json.load(f)

    def test_transforms_full_session(self, sample_session):
        """Test transformation of full session."""
        result = transform_gemini_v1(sample_session, "/test/session.json")

        # 7 original messages:
        # - 1 user = 1 msg
        # - 4 gemini messages expand to: assistant + tool_call + tool_result (or just tool_call if cancelled)
        #   = 3 + 3 + 3 + 2 = 11 msgs
        # - 1 error = 1 msg
        # - 1 info = 1 msg
        # Total: 1 + 11 + 1 + 1 = 14
        assert len(result) == 14

    def test_transforms_user_message(self, sample_session):
        """Test transformation of user message."""
        result = transform_gemini_v1(sample_session, "/test/session.json")

        user_msg = result[0]
        assert user_msg.msg_type == "user"
        assert user_msg.content == "Build a blog app with Flask"
        assert user_msg.source == "gemini_cli"
        assert user_msg.session_id == "test-session-gemini-001"

    def test_transforms_gemini_message_with_tools(self, sample_session):
        """Test transformation of gemini message with tool calls."""
        result = transform_gemini_v1(sample_session, "/test/session.json")

        # Assistant message (first gemini message)
        assistant_msg = result[1]
        assert assistant_msg.msg_type == "assistant"
        assert "Flask blog" in assistant_msg.content
        assert assistant_msg.model == "gemini-2.5-pro"
        assert assistant_msg.tokens.input == 6610
        assert assistant_msg.tokens.output == 144
        assert assistant_msg.tokens.thinking == 242
        assert assistant_msg.thinking is not None
        assert "Beginning the Blog Build" in assistant_msg.thinking
        assert "Planning Architecture" in assistant_msg.thinking  # Multiple thoughts

        # Tool call
        tool_call_msg = result[2]
        assert tool_call_msg.msg_type == "tool_call"
        assert tool_call_msg.tool_call.name == "write_file"
        assert tool_call_msg.tool_call.input["file_path"] == "app.py"

        # Tool result (newContent from file write)
        tool_result_msg = result[3]
        assert tool_result_msg.msg_type == "tool_result"
        assert tool_result_msg.tool_result.status == "success"
        # File write result shows the file content
        assert "Flask" in tool_result_msg.tool_result.output

    def test_transforms_shell_command_with_string_result(self, sample_session):
        """Test transformation of shell command with string resultDisplay."""
        result = transform_gemini_v1(sample_session, "/test/session.json")

        # Second gemini message (shell command)
        shell_result = result[6]  # assistant=4, tool_call=5, tool_result=6
        assert shell_result.msg_type == "tool_result"
        assert shell_result.tool_result.status == "success"
        assert "Flask" in shell_result.tool_result.output

    def test_transforms_error_status_tool(self, sample_session):
        """Test transformation of tool call with error status."""
        result = transform_gemini_v1(sample_session, "/test/session.json")

        # Third gemini message has error status
        error_result = result[9]  # assistant=7, tool_call=8, tool_result=9
        assert error_result.msg_type == "tool_result"
        assert error_result.tool_result.status == "failure"
        assert "Port 5000" in error_result.tool_result.output

    def test_transforms_cancelled_tool(self, sample_session):
        """Test transformation of cancelled tool call."""
        result = transform_gemini_v1(sample_session, "/test/session.json")

        # Fourth gemini message has cancelled status - only tool_call, no tool_result
        cancelled_call = result[11]  # assistant=10, tool_call=11
        assert cancelled_call.msg_type == "tool_call"
        assert cancelled_call.tool_call.name == "write_todos"

    def test_transforms_error_message(self, sample_session):
        """Test transformation of error message."""
        result = transform_gemini_v1(sample_session, "/test/session.json")

        error_msg = result[12]
        assert error_msg.msg_type == "error"
        assert "429" in error_msg.content

    def test_transforms_info_message(self, sample_session):
        """Test transformation of info message."""
        result = transform_gemini_v1(sample_session, "/test/session.json")

        info_msg = result[13]
        assert info_msg.msg_type == "info"
        assert "Rate limit" in info_msg.content


class TestClaudeCodeRealSession:
    """Test with a real Claude Code session file."""

    def test_can_parse_real_session_with_thinking(self):
        """Test parsing a real session file that includes thinking content."""

        # Find any .jsonl file under ~/.claude/projects/
        claude_dir = Path(os.path.expanduser("~/.claude/projects"))
        candidates = sorted(claude_dir.glob("*/*.jsonl"), key=lambda p: p.stat().st_size, reverse=True)

        if not candidates:
            pytest.skip("No Claude Code session files found on this machine")

        real_session = candidates[0]

        messages = []
        with open(real_session) as f:
            for line_num, line in enumerate(f, 1):
                if line.strip():
                    data = json.loads(line)
                    result = transform_claude_v1(data, str(real_session), line_num)
                    messages.extend(result)

        # Should have parsed some messages
        assert len(messages) > 0

        # Should have assistant messages with model
        assistant_msgs = [m for m in messages if m.msg_type == "assistant"]
        assert len(assistant_msgs) > 0

        # If thinking content exists, verify it looks like real text
        msgs_with_thinking = [m for m in assistant_msgs if m.thinking]
        for msg in msgs_with_thinking:
            assert not msg.thinking.startswith("gAAAAA"), "Thinking appears to be encrypted"
            assert len(msg.thinking) > 10, "Thinking content too short"


class TestGeminiCliRealSession:
    """Test with a real Gemini CLI session file."""

    def test_can_parse_real_session(self):
        """Test parsing a real Gemini session file."""

        gemini_dir = Path(os.path.expanduser("~/.gemini/tmp"))
        if not gemini_dir.exists():
            pytest.skip("Gemini CLI directory not found")

        candidates = sorted(
            gemini_dir.glob("*/chats/session-*.json"),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        if not candidates:
            pytest.skip("No Gemini session files found on this machine")

        real_session = candidates[0]

        with open(real_session) as f:
            session_data = json.load(f)

        messages = transform_gemini_v1(session_data, str(real_session))

        # Should have parsed many messages
        assert len(messages) > 0

        # Should have various message types
        msg_types = set(m.msg_type for m in messages)
        assert "user" in msg_types
        assert "assistant" in msg_types

        # Should have tool calls and results
        tool_calls = [m for m in messages if m.msg_type == "tool_call"]
        tool_results = [m for m in messages if m.msg_type == "tool_result"]
        assert len(tool_calls) > 0, "Expected tool calls in real session"
        assert len(tool_results) > 0, "Expected tool results in real session"

        # Assistant messages should have model info
        assistant_msgs = [m for m in messages if m.msg_type == "assistant"]
        models = set(m.model for m in assistant_msgs if m.model)
        assert len(models) > 0, "Expected model info in assistant messages"
        # Should have gemini models
        assert any("gemini" in m for m in models), f"Expected gemini model, got: {models}"

        # Some should have thinking/thoughts
        msgs_with_thinking = [m for m in assistant_msgs if m.thinking]
        assert len(msgs_with_thinking) > 0, "Expected messages with thinking content"


class TestNormalizedMessageSchema:
    """Tests for the NormalizedMessage schema."""

    def test_has_required_fields(self):
        """Test that NormalizedMessage has all required fields."""
        msg = NormalizedMessage(
            id="test-id",
            session_id="session-123",
            source="claude_code",
            source_schema_version=1,
            msg_type="user",
            timestamp="2026-02-04T10:00:00.000Z",
        )

        assert msg.id == "test-id"
        assert msg.session_id == "session-123"
        assert msg.source == "claude_code"
        assert msg.source_schema_version == 1
        assert msg.msg_type == "user"
        assert msg.timestamp == "2026-02-04T10:00:00.000Z"

        # Defaults
        assert msg.content is None
        assert msg.tokens.input == 0
        assert msg.tool_call is None
        assert msg.tool_result is None
        assert msg.thinking is None
        assert msg.model is None
        assert msg.raw_file_path == ""
        assert msg.raw_line_number is None

        # Observability defaults
        assert msg.progress_data is None
        assert msg.system_event_data is None
        assert msg.queue_operation_data is None
        assert msg.raw_data is None

    def test_observability_message_types(self):
        """Test that observability message types are supported."""

        # Progress message
        progress_msg = NormalizedMessage(
            id="progress-1",
            session_id="session-123",
            source="claude_code",
            source_schema_version=1,
            msg_type="progress",
            timestamp="2026-02-04T10:00:00.000Z",
            progress_data=ProgressData(
                progress_type="hook_progress",
                hook_info=HookInfo(
                    event="PostToolUse",
                    name="PostToolUse:Write",
                    command="callback",
                    tool_use_id="tool-123",
                ),
            ),
        )
        assert progress_msg.msg_type == "progress"
        assert progress_msg.progress_data.progress_type == "hook_progress"
        assert progress_msg.progress_data.hook_info.event == "PostToolUse"

        # System event message
        system_msg = NormalizedMessage(
            id="system-1",
            session_id="session-123",
            source="claude_code",
            source_schema_version=1,
            msg_type="system_event",
            timestamp="2026-02-04T10:00:00.000Z",
            system_event_data=SystemEventData(
                subtype="turn_duration",
                duration_ms=5000,
            ),
        )
        assert system_msg.msg_type == "system_event"
        assert system_msg.system_event_data.duration_ms == 5000

        # Queue operation message
        queue_msg = NormalizedMessage(
            id="queue-1",
            session_id="session-123",
            source="claude_code",
            source_schema_version=1,
            msg_type="queue_operation",
            timestamp="2026-02-04T10:00:00.000Z",
            queue_operation_data=QueueOperationData(
                operation="enqueue",
                task_id="task-001",
                status="running",
                summary="Background task running",
            ),
        )
        assert queue_msg.msg_type == "queue_operation"
        assert queue_msg.queue_operation_data.task_id == "task-001"
