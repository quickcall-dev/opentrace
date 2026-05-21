# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Transform Cursor IDE session data to unified format.

HACK: Synthetic sequential timestamps
======================================
Cursor transcript files (.txt) do NOT contain per-message timestamps.
The only timestamp available is the file's mtime, which means every message
in a session gets the exact same timestamp. This completely breaks message
ordering in the database — user messages, assistant messages, tool calls,
and tool results all appear simultaneous and sort arbitrarily.

Workaround: we add 1 millisecond per message to the base file timestamp.
Message 0 gets mtime+0ms, message 1 gets mtime+1ms, etc. This preserves
the sequential ordering from the transcript file while making it clear
these are NOT real timestamps.

Limitations:
- Timestamps are synthetic — they do NOT reflect when messages actually occurred.
- Tool call results are missing from transcripts entirely (Cursor doesn't write
  them to .txt files), so tool_result messages have empty/partial output.
- The real message timing (think time, response latency) is lost.
- For accurate timestamps and tool results, use cursor_vscdb source instead.
"""

import os
import re
import uuid
from datetime import datetime, timedelta, timezone

from opentrace.schemas.cursor import (
    CursorAgentTranscript,
    CursorComposerEntry,
    CursorToolInvocation,
    CursorTranscriptMessage,
)
from opentrace.schemas.unified import (
    NormalizedMessage,
    ToolCall,
    ToolResult,
)


def extract_session_id(file_path: str) -> str:
    """Extract session ID (composerId) from Cursor transcript file path.

    Path format: ~/.cursor/projects/{slug}/agent-transcripts/{composerId}.txt
    Example: ~/.cursor/projects/-Users-bob-myproject/agent-transcripts/abc123-def456.txt
    Returns: abc123-def456
    """
    match = re.search(r"/([^/]+)\.txt$", file_path)
    if match:
        return match.group(1)
    return file_path


def transform_cursor_v1(
    transcript: CursorAgentTranscript,
    file_path: str,
) -> list[NormalizedMessage]:
    """Transform a Cursor agent transcript to normalized messages.

    Args:
        transcript: Parsed transcript from parse_agent_transcript()
        file_path: Path to the source file

    Returns:
        List of NormalizedMessage objects. Each message (user/assistant)
        becomes one message, and tool calls/results become separate messages.
    """
    session_id = transcript.get("composer_id") or extract_session_id(file_path)
    messages: list[NormalizedMessage] = []
    msg_index = 0

    # Use file mtime as base timestamp. Each message gets +1ms to preserve
    # sequential ordering. See module docstring for why this hack exists.
    base_dt: datetime | None = None
    try:
        mtime = os.path.getmtime(file_path)
        base_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    except OSError:
        pass

    for msg in transcript.get("messages", []):
        result = transform_transcript_message(msg, session_id, file_path, msg_index, base_dt)
        messages.extend(result)
        msg_index += len(result)

    return messages


def transform_transcript_message(
    msg: CursorTranscriptMessage,
    session_id: str,
    file_path: str,
    msg_index: int,
    base_dt: datetime | None = None,
) -> list[NormalizedMessage]:
    """Transform a single transcript message to normalized messages.

    Args:
        msg: Parsed message from transcript
        session_id: Session identifier (composerId)
        file_path: Path to the source file
        msg_index: Index for generating unique message IDs
        base_dt: Base datetime for synthetic sequential timestamps (see module docstring)

    Returns:
        List of NormalizedMessage objects. User messages produce one message.
        Assistant messages may produce multiple (text + tool calls + tool results).
    """
    role = msg.get("role", "user")
    file_ts = _sequential_ts(base_dt, msg_index) if base_dt else ""

    if role == "user":
        return [_transform_user_message(msg, session_id, file_path, msg_index, file_ts)]
    else:
        return _transform_assistant_message(msg, session_id, file_path, msg_index, base_dt)


def _transform_user_message(
    msg: CursorTranscriptMessage,
    session_id: str,
    file_path: str,
    msg_index: int,
    file_ts: str = "",
) -> NormalizedMessage:
    """Transform a user message."""
    return NormalizedMessage(
        id=f"{session_id}-{msg_index}",
        session_id=session_id,
        source="cursor",
        source_schema_version=1,
        msg_type="user",
        timestamp=file_ts,
        content=msg.get("content", ""),
        raw_file_path=file_path,
        raw_line_number=None,
    )


def _transform_assistant_message(
    msg: CursorTranscriptMessage,
    session_id: str,
    file_path: str,
    msg_index: int,
    base_dt: datetime | None = None,
) -> list[NormalizedMessage]:
    """Transform an assistant message with potential tool calls.

    Returns multiple messages:
    - One assistant message with content and thinking
    - Separate messages for each tool call and tool result

    Each sub-message gets its own sequential timestamp offset from base_dt.
    """
    messages: list[NormalizedMessage] = []
    content = msg.get("content", "")
    thinking = msg.get("thinking")
    tool_calls = msg.get("tool_calls", [])
    sub_offset = 0  # offset within this assistant turn

    # Create the main assistant message if there's content or thinking
    if content or thinking:
        ts = _sequential_ts(base_dt, msg_index + sub_offset) if base_dt else ""
        messages.append(
            NormalizedMessage(
                id=f"{session_id}-{msg_index}",
                session_id=session_id,
                source="cursor",
                source_schema_version=1,
                msg_type="assistant",
                timestamp=ts,
                content=content if content else None,
                thinking=thinking,
                raw_file_path=file_path,
                raw_line_number=None,
            )
        )
        sub_offset += 1

    # Transform tool invocations, tracking call IDs for result linking
    last_call_id: str | None = None
    for i, tool in enumerate(tool_calls):
        ts = _sequential_ts(base_dt, msg_index + sub_offset) if base_dt else ""
        tool_messages = transform_tool_invocation(
            tool, session_id, file_path, msg_index + sub_offset, ts,
            preceding_call_id=last_call_id,
        )
        messages.extend(tool_messages)
        sub_offset += len(tool_messages)
        # Track the call_id so subsequent tool_results can reference it
        if tool.get("type", "tool_call") == "tool_call":
            tool_id = f"{session_id}-tool-{msg_index + sub_offset - 1}"
            last_call_id = tool_id
        else:
            last_call_id = None

    return messages


def transform_tool_invocation(
    tool: CursorToolInvocation,
    session_id: str,
    file_path: str,
    msg_index: int,
    file_ts: str = "",
    preceding_call_id: str | None = None,
) -> list[NormalizedMessage]:
    """Transform a tool call or result to normalized message.

    Args:
        tool: Tool invocation from transcript
        session_id: Session identifier
        file_path: Path to source file
        msg_index: Index for message ID
        file_ts: Fallback timestamp from file mtime
        preceding_call_id: ID of the preceding tool_call, used to link
            tool_results back to their corresponding tool_call.

    Returns:
        List containing one NormalizedMessage (either tool_call or tool_result)
    """
    tool_type = tool.get("type", "tool_call")
    tool_name = tool.get("tool_name", "")
    tool_id = f"{session_id}-tool-{msg_index}"

    if tool_type == "tool_call":
        return [
            NormalizedMessage(
                id=tool_id,
                session_id=session_id,
                source="cursor",
                source_schema_version=1,
                msg_type="tool_call",
                timestamp=file_ts,
                content=None,
                tool_call=ToolCall(
                    id=tool_id,
                    name=tool_name,
                    input=tool.get("parameters", {}),
                ),
                raw_file_path=file_path,
                raw_line_number=None,
            )
        ]
    else:  # tool_result
        result_content = tool.get("result") or ""
        # Link back to the preceding tool_call's ID if available
        call_id = preceding_call_id or tool_id
        return [
            NormalizedMessage(
                id=tool_id,
                session_id=session_id,
                source="cursor",
                source_schema_version=1,
                msg_type="tool_result",
                timestamp=file_ts,
                content=None,
                tool_result=ToolResult(
                    call_id=call_id,
                    output=result_content,
                    status="success",  # Cursor transcripts don't indicate failure
                ),
                raw_file_path=file_path,
                raw_line_number=None,
            )
        ]


def _sequential_ts(base_dt: datetime, offset: int) -> str:
    """Add offset milliseconds to base datetime and return ISO 8601 string.

    HACK: This produces synthetic timestamps to preserve message ordering.
    These are NOT real timestamps — see module docstring.
    """
    return (base_dt + timedelta(milliseconds=offset)).isoformat()


def transform_composer_metadata(
    composer: CursorComposerEntry,
    file_path: str,
) -> NormalizedMessage:
    """Transform composer metadata to a system message.

    This captures session metadata like mode, creation time, and stats
    as a system-type message for observability.

    Args:
        composer: Composer entry from composer.composerData
        file_path: Source database path

    Returns:
        NormalizedMessage with composer metadata in raw_data
    """
    composer_id = composer.get("composerId", str(uuid.uuid4()))
    created_at = composer.get("createdAt")

    # Convert Unix timestamp (ms) to ISO 8601 if available
    timestamp = ""
    if created_at:
        dt = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)
        timestamp = dt.isoformat()

    return NormalizedMessage(
        id=f"{composer_id}-meta",
        session_id=composer_id,
        source="cursor",
        source_schema_version=1,
        msg_type="system",
        timestamp=timestamp,
        content=f"Cursor {composer.get('unifiedMode', 'chat')} session: {composer.get('name', 'Untitled')}",
        raw_data=dict(composer),  # Preserve full metadata
        raw_file_path=file_path,
        raw_line_number=None,
    )
