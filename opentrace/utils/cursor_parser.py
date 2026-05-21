# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Cursor file parsers for transcripts, terminals, and MCP definitions.

Parses file-based Cursor data:
- Agent transcripts: ~/.cursor/projects/<slug>/agent-transcripts/<composerId>.txt
- Terminal sessions: ~/.cursor/projects/<slug>/terminals/<id>.txt
- MCP tool definitions: ~/.cursor/projects/<slug>/mcps/<server>/tools/<name>.json
- MCP server metadata: ~/.cursor/projects/<slug>/mcps/<server>/SERVER_METADATA.json
"""

import re
from pathlib import Path

from opentrace.schemas.cursor import (
    CursorAgentTranscript,
    CursorTerminalSession,
    CursorToolInvocation,
    CursorTranscriptMessage,
)


def parse_agent_transcript(file_path: str) -> CursorAgentTranscript:
    """Parse agent transcript .txt file.

    Args:
        file_path: Path to the transcript file

    Returns:
        Parsed transcript with messages, tool calls, and thinking blocks

    Transcript format:
        user:
        <user_query>
        User message here
        </user_query>

        assistant:
        <think>
        Agent reasoning...
        </think>

        Response text...

        [Tool call] ToolName
          param1: value1

        [Tool result] ToolName
        Result content
    """
    path = Path(file_path)
    if not path.exists():
        return {
            "composer_id": path.stem,
            "file_path": str(path),
            "messages": [],
        }

    content = path.read_text(encoding="utf-8")
    composer_id = path.stem  # filename without extension is composerId

    messages = _parse_transcript_content(content)

    return {
        "composer_id": composer_id,
        "file_path": str(path),
        "messages": messages,
        "raw_content": content,
    }


def _parse_transcript_content(content: str) -> list[CursorTranscriptMessage]:
    """Parse transcript content into messages.

    Handles:
    - user: blocks with <user_query> tags
    - assistant: blocks with optional <think> tags
    - [Tool call] and [Tool result] sections
    """
    messages: list[CursorTranscriptMessage] = []

    # Split by message boundaries (user: or assistant:)
    # Use regex to find message starts
    message_pattern = re.compile(r"^(user|assistant):\s*$", re.MULTILINE)

    parts = message_pattern.split(content)

    # parts will be: [preamble, role1, content1, role2, content2, ...]
    # Skip preamble (index 0), then process pairs
    i = 1
    while i < len(parts) - 1:
        role = parts[i].strip()
        msg_content = parts[i + 1] if i + 1 < len(parts) else ""

        if role == "user":
            messages.append(_parse_user_message(msg_content))
        elif role == "assistant":
            messages.append(_parse_assistant_message(msg_content))

        i += 2

    return messages


def _parse_user_message(content: str) -> CursorTranscriptMessage:
    """Parse a user message block.

    Extracts content from <user_query>...</user_query> tags.
    """
    # Extract content from <user_query> tags
    query_match = re.search(
        r"<user_query>\s*(.*?)\s*</user_query>", content, re.DOTALL
    )

    if query_match:
        extracted = query_match.group(1).strip()
    else:
        # Fallback: use entire content
        extracted = content.strip()

    return {
        "role": "user",
        "content": extracted,
        "thinking": None,
        "tool_calls": [],
    }


def _parse_assistant_message(content: str) -> CursorTranscriptMessage:
    """Parse an assistant message block.

    Extracts:
    - <think>...</think> blocks into thinking field
    - [Tool call] and [Tool result] into tool_calls
    - Remaining text as content
    """
    # Extract thinking blocks
    thinking = None
    think_match = re.search(r"<think>\s*(.*?)\s*</think>", content, re.DOTALL)
    if think_match:
        thinking = think_match.group(1).strip()
        # Remove thinking block from content for further processing
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)

    # Extract tool calls and results
    tool_calls = _extract_tool_invocations(content)

    # Remove tool sections from content to get clean text
    clean_content = _remove_tool_sections(content).strip()

    return {
        "role": "assistant",
        "content": clean_content,
        "thinking": thinking,
        "tool_calls": tool_calls,
    }


def _extract_tool_invocations(content: str) -> list[CursorToolInvocation]:
    """Extract [Tool call] and [Tool result] sections from content."""
    tool_calls: list[CursorToolInvocation] = []

    # Pattern for tool calls: [Tool call] ToolName followed by indented params
    tool_call_pattern = re.compile(
        r"\[Tool call\]\s+(\w+)\s*\n((?:[ \t]+\w+:.*\n?)*)",
        re.MULTILINE,
    )

    for match in tool_call_pattern.finditer(content):
        tool_name = match.group(1)
        params_block = match.group(2)

        # Parse parameters (indented key: value lines)
        parameters = {}
        for line in params_block.strip().split("\n"):
            line = line.strip()
            if ":" in line:
                key, value = line.split(":", 1)
                parameters[key.strip()] = value.strip()

        tool_calls.append({
            "type": "tool_call",
            "tool_name": tool_name,
            "parameters": parameters,
            "result": None,
        })

    # Pattern for tool results: [Tool result] ToolName followed by content
    tool_result_pattern = re.compile(
        r"\[Tool result\]\s+(\w+)\s*\n?(.*?)(?=\[Tool (?:call|result)\]|assistant:|user:|$)",
        re.DOTALL,
    )

    for match in tool_result_pattern.finditer(content):
        tool_name = match.group(1)
        result_content = match.group(2).strip()

        tool_calls.append({
            "type": "tool_result",
            "tool_name": tool_name,
            "parameters": {},
            "result": result_content if result_content else None,
        })

    return tool_calls


def _remove_tool_sections(content: str) -> str:
    """Remove [Tool call] and [Tool result] sections from content."""
    # Remove tool call blocks
    content = re.sub(
        r"\[Tool call\]\s+\w+\s*\n(?:[ \t]+\w+:.*\n?)*",
        "",
        content,
        flags=re.MULTILINE,
    )
    # Remove tool result blocks
    content = re.sub(
        r"\[Tool result\]\s+\w+\s*\n?.*?(?=\[Tool (?:call|result)\]|assistant:|user:|$)",
        "",
        content,
        flags=re.DOTALL,
    )
    return content


def parse_terminal_session(file_path: str) -> CursorTerminalSession:
    """Parse terminal session with YAML frontmatter.

    Args:
        file_path: Path to the terminal session file

    Returns:
        Parsed terminal session with pid, cwd, and content

    Format:
        ---
        pid: 79706
        cwd: /path/to/workspace
        ---
        <terminal output content>
    """
    path = Path(file_path)
    if not path.exists():
        return {
            "session_id": path.stem,
            "file_path": str(path),
            "pid": None,
            "cwd": None,
            "content": "",
        }

    content = path.read_text(encoding="utf-8")
    session_id = path.stem

    # Parse YAML frontmatter
    pid = None
    cwd = None
    body = content

    if content.startswith("---"):
        # Find end of frontmatter
        end_match = re.search(r"\n---\s*\n", content[3:])
        if end_match:
            frontmatter = content[3 : 3 + end_match.start()]
            body = content[3 + end_match.end() :]

            # Extract pid and cwd from frontmatter
            pid_match = re.search(r"^pid:\s*(\d+)", frontmatter, re.MULTILINE)
            if pid_match:
                pid = int(pid_match.group(1))

            cwd_match = re.search(r"^cwd:\s*(.+)$", frontmatter, re.MULTILINE)
            if cwd_match:
                cwd = cwd_match.group(1).strip()

    return {
        "session_id": session_id,
        "file_path": str(path),
        "pid": pid,
        "cwd": cwd,
        "content": body,
    }


