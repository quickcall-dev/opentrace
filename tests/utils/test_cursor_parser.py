# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for Cursor file parsers."""

from pathlib import Path

import pytest

from opentrace.utils.cursor_parser import (
    parse_agent_transcript,
    parse_terminal_session,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestParseAgentTranscript:
    """Tests for parse_agent_transcript function."""

    def test_parse_sample_transcript(self):
        """Test parsing the sample transcript fixture."""
        result = parse_agent_transcript(
            str(FIXTURES_DIR / "cursor_transcript_sample.txt")
        )

        assert result["composer_id"] == "cursor_transcript_sample"
        assert result["file_path"].endswith("cursor_transcript_sample.txt")
        assert len(result["messages"]) >= 4  # At least 4 messages in sample

    def test_parse_user_message(self):
        """Test that user messages are parsed correctly."""
        result = parse_agent_transcript(
            str(FIXTURES_DIR / "cursor_transcript_sample.txt")
        )

        # First message should be user
        first_msg = result["messages"][0]
        assert first_msg["role"] == "user"
        assert "fibonacci" in first_msg["content"].lower()
        assert first_msg["thinking"] is None
        assert first_msg["tool_calls"] == []

    def test_parse_assistant_thinking(self):
        """Test that thinking blocks are extracted."""
        result = parse_agent_transcript(
            str(FIXTURES_DIR / "cursor_transcript_sample.txt")
        )

        # Find assistant message with thinking
        assistant_msgs = [m for m in result["messages"] if m["role"] == "assistant"]
        assert len(assistant_msgs) > 0

        # At least one should have thinking
        thinking_msgs = [m for m in assistant_msgs if m.get("thinking")]
        assert len(thinking_msgs) > 0

    def test_parse_tool_calls(self):
        """Test that tool calls are extracted."""
        result = parse_agent_transcript(
            str(FIXTURES_DIR / "cursor_transcript_sample.txt")
        )

        # Find messages with tool calls
        all_tool_calls = []
        for msg in result["messages"]:
            all_tool_calls.extend(msg.get("tool_calls", []))

        # Should have Write tool calls
        write_calls = [t for t in all_tool_calls if t["tool_name"] == "Write"]
        assert len(write_calls) > 0

    def test_nonexistent_file(self):
        """Test handling of nonexistent files."""
        result = parse_agent_transcript("/nonexistent/path/transcript.txt")

        assert result["composer_id"] == "transcript"
        assert result["messages"] == []


class TestParseTerminalSession:
    """Tests for parse_terminal_session function."""

    def test_parse_sample_terminal(self):
        """Test parsing the sample terminal fixture."""
        result = parse_terminal_session(
            str(FIXTURES_DIR / "cursor_terminal_sample.txt")
        )

        assert result["session_id"] == "cursor_terminal_sample"
        assert result["pid"] == 79706
        assert result["cwd"] == "/Users/test/work/opentrace/trace"
        assert "pytest" in result["content"]

    def test_parse_frontmatter(self):
        """Test YAML frontmatter extraction."""
        result = parse_terminal_session(
            str(FIXTURES_DIR / "cursor_terminal_sample.txt")
        )

        assert result["pid"] is not None
        assert result["cwd"] is not None

    def test_nonexistent_file(self):
        """Test handling of nonexistent files."""
        result = parse_terminal_session("/nonexistent/path/terminal.txt")

        assert result["session_id"] == "terminal"
        assert result["pid"] is None
        assert result["cwd"] is None
        assert result["content"] == ""


class TestRealCursorData:
    """Tests using real Cursor data from the system.

    These tests are skipped if Cursor data doesn't exist.
    """

    @pytest.fixture
    def cursor_home(self):
        """Get Cursor home directory."""
        path = Path.home() / ".cursor"
        if not path.exists():
            pytest.skip("Cursor not installed")
        return path

    def test_parse_real_transcript(self, cursor_home):
        """Test parsing a real transcript if available."""
        projects_dir = cursor_home / "projects"
        if not projects_dir.exists():
            pytest.skip("No projects directory")

        # Find first transcript
        transcript = None
        for project_dir in projects_dir.iterdir():
            transcripts = project_dir / "agent-transcripts"
            if transcripts.exists():
                for f in transcripts.glob("*.txt"):
                    transcript = f
                    break
            if transcript:
                break

        if not transcript:
            pytest.skip("No transcripts found")

        result = parse_agent_transcript(str(transcript))
        assert result["composer_id"]
        assert isinstance(result["messages"], list)
