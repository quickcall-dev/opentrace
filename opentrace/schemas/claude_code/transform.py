# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Transform Claude Code v1 session data to unified format."""

import re
from typing import Any

from opentrace.schemas.unified import (
    HookInfo,
    NormalizedMessage,
    ProgressData,
    QueueOperationData,
    SystemEventData,
    TokenUsage,
    ToolCall,
    ToolResult,
)


def extract_session_id(file_path: str) -> str:
    """Extract session ID from Claude Code file path.

    Path format: ~/.claude/projects/{path-encoded-dir}/{session-id}.jsonl
    Example: ~/.claude/projects/-Users-bob-myproject/abc123-def456.jsonl
    Returns: abc123-def456
    """
    match = re.search(r"/([^/]+)\.jsonl$", file_path)
    if match:
        return match.group(1)
    return file_path


def extract_tokens(usage: dict[str, Any]) -> TokenUsage:
    """Extract token usage from Claude Code usage dict."""
    return TokenUsage(
        input=usage.get("input_tokens", 0),
        output=usage.get("output_tokens", 0),
        cached=usage.get("cache_read_input_tokens", 0),
        thinking=0,  # Claude Code doesn't separate thinking tokens
    )


def _extract_tool_results(
    blocks: list,
    line_uuid: str,
    session_id: str,
    file_path: str,
    line_num: int,
    timestamp: str,
    use_is_error: bool = False,
) -> list[NormalizedMessage]:
    """Extract tool_result messages from content blocks.

    Args:
        blocks: List of content blocks to scan for tool_result entries.
        line_uuid: UUID from the parent line, used to build message IDs.
        session_id: Session identifier.
        file_path: Path to the source file.
        line_num: Line number in the source file.
        timestamp: Message timestamp.
        use_is_error: If True, check block's is_error field for status.
            If False, default to "success".
    """
    messages = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        tool_output = block.get("content", "")
        if isinstance(tool_output, list):
            tool_output = "\n".join(
                p.get("text", str(p)) if isinstance(p, dict) else str(p)
                for p in tool_output
            )
        status = "failure" if use_is_error and block.get("is_error") else "success"
        messages.append(
            NormalizedMessage(
                id=f"{line_uuid}-{block.get('tool_use_id', '')}",
                session_id=session_id,
                source="claude_code",
                source_schema_version=1,
                msg_type="tool_result",
                timestamp=timestamp,
                content=None,
                tool_result=ToolResult(
                    call_id=block.get("tool_use_id", ""),
                    output=str(tool_output),
                    status=status,
                ),
                raw_file_path=file_path,
                raw_line_number=line_num,
            )
        )
    return messages


def transform_claude_v1(
    line: dict[str, Any],
    file_path: str,
    line_num: int,
) -> list[NormalizedMessage]:
    """Transform a Claude Code JSONL line to normalized messages.

    Args:
        line: Parsed JSON object from a JSONL line
        file_path: Path to the source file
        line_num: Line number in the source file (1-indexed)

    Returns:
        List of NormalizedMessage objects. May return multiple messages
        for assistant messages that contain both text and tool calls.
        All message types are captured for observability.
    """
    line_type = line.get("type")
    session_id = line.get("sessionId") or extract_session_id(file_path)

    # Core conversation types
    if line_type == "user":
        return _transform_user_message(line, session_id, file_path, line_num)
    elif line_type == "assistant":
        return _transform_assistant_message(line, session_id, file_path, line_num)
    elif line_type == "result":
        return _transform_result_message(line, session_id, file_path, line_num)

    # Observability types
    elif line_type == "progress":
        return _transform_progress_message(line, session_id, file_path, line_num)
    elif line_type == "system":
        return _transform_system_message(line, session_id, file_path, line_num)
    elif line_type == "queue-operation":
        return _transform_queue_operation(line, session_id, file_path, line_num)
    elif line_type == "file-history-snapshot":
        return _transform_file_snapshot(line, session_id, file_path, line_num)
    elif line_type == "summary":
        return _transform_summary(line, session_id, file_path, line_num)

    # Unknown type - still capture it with raw_data
    return [
        NormalizedMessage(
            id=line.get("uuid", f"unknown-{line_num}"),
            session_id=session_id,
            source="claude_code",
            source_schema_version=1,
            msg_type="info",
            timestamp=line.get("timestamp", ""),
            content=f"Unknown message type: {line_type}",
            raw_data=line,
            raw_file_path=file_path,
            raw_line_number=line_num,
        )
    ]


def _transform_user_message(
    line: dict[str, Any],
    session_id: str,
    file_path: str,
    line_num: int,
) -> list[NormalizedMessage]:
    """Transform a Claude Code user message."""
    message = line.get("message", {})
    content = message.get("content")

    # Check if this is a tool result (content is a list with tool_result blocks)
    if isinstance(content, list):
        return _extract_tool_results(
            content, line["uuid"], session_id, file_path, line_num,
            line.get("timestamp", ""), use_is_error=False,
        )

    # Regular user message with string content
    return [
        NormalizedMessage(
            id=line.get("uuid", ""),
            session_id=session_id,
            source="claude_code",
            source_schema_version=1,
            msg_type="user",
            timestamp=line.get("timestamp", ""),
            content=content if isinstance(content, str) else str(content),
            raw_file_path=file_path,
            raw_line_number=line_num,
        )
    ]


def _transform_assistant_message(
    line: dict[str, Any],
    session_id: str,
    file_path: str,
    line_num: int,
) -> list[NormalizedMessage]:
    """Transform a Claude Code assistant message.

    An assistant message may contain multiple content blocks:
    - text: Regular response text
    - thinking: Reasoning/thinking content
    - tool_use: Tool invocation

    We produce separate NormalizedMessages for:
    - Combined text + thinking as a single "assistant" message
    - Each tool_use as a separate "tool_call" message
    """
    message = line.get("message", {})
    content_blocks = message.get("content", [])

    # Usage is inside message object for assistant messages
    usage = message.get("usage", {})
    tokens = extract_tokens(usage)

    # Model is inside message object
    model = message.get("model")

    messages = []
    text_parts = []
    thinking_parts = []

    for block in content_blocks:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")

        if block_type == "text":
            text_parts.append(block.get("text", ""))

        elif block_type == "thinking":
            thinking_parts.append(block.get("thinking", ""))

        elif block_type == "tool_use":
            # Each tool_use becomes its own message
            # Note: tokens are NOT attached here to avoid double-counting;
            # they are only on the assistant message from the same turn.
            messages.append(
                NormalizedMessage(
                    id=block.get("id", f"{line.get('uuid', '')}-tool"),
                    session_id=session_id,
                    source="claude_code",
                    source_schema_version=1,
                    msg_type="tool_call",
                    timestamp=line.get("timestamp", ""),
                    content=None,
                    tool_call=ToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        input=block.get("input", {}),
                    ),
                    model=model,
                    raw_file_path=file_path,
                    raw_line_number=line_num,
                )
            )

    # Combine text and thinking into one assistant message
    combined_text = "\n\n".join(text_parts) if text_parts else None
    combined_thinking = "\n\n".join(thinking_parts) if thinking_parts else None

    if combined_text or combined_thinking:
        messages.insert(
            0,  # Put assistant message before tool calls
            NormalizedMessage(
                id=line.get("uuid", ""),
                session_id=session_id,
                source="claude_code",
                source_schema_version=1,
                msg_type="assistant",
                timestamp=line.get("timestamp", ""),
                content=combined_text,
                tokens=tokens,
                thinking=combined_thinking,
                model=model,
                raw_file_path=file_path,
                raw_line_number=line_num,
            ),
        )

    return messages


def _transform_result_message(
    line: dict[str, Any],
    session_id: str,
    file_path: str,
    line_num: int,
) -> list[NormalizedMessage]:
    """Transform a Claude Code result message (tool result outside user message)."""
    message = line.get("message", {})
    content = message.get("content")

    if isinstance(content, list):
        return _extract_tool_results(
            content, line.get("uuid", ""), session_id, file_path, line_num,
            line.get("timestamp", ""), use_is_error=True,
        )

    return []


def _transform_progress_message(
    line: dict[str, Any],
    session_id: str,
    file_path: str,
    line_num: int,
) -> list[NormalizedMessage]:
    """Transform a Claude Code progress message."""
    data = line.get("data", {})
    progress_type = data.get("type", "unknown")

    hook_info = None
    if progress_type == "hook_progress":
        hook_info = HookInfo(
            event=data.get("hookEvent", ""),
            name=data.get("hookName", ""),
            command=data.get("command"),
            tool_use_id=line.get("toolUseID"),
        )

    progress_data = ProgressData(
        progress_type=progress_type,
        hook_info=hook_info,
        stdout=data.get("stdout"),
        stderr=data.get("stderr"),
    )

    return [
        NormalizedMessage(
            id=line.get("uuid", f"progress-{line_num}"),
            session_id=session_id,
            source="claude_code",
            source_schema_version=1,
            msg_type="progress",
            timestamp=line.get("timestamp", ""),
            progress_data=progress_data,
            raw_file_path=file_path,
            raw_line_number=line_num,
        )
    ]


def _transform_system_message(
    line: dict[str, Any],
    session_id: str,
    file_path: str,
    line_num: int,
) -> list[NormalizedMessage]:
    """Transform a Claude Code system event message."""
    subtype = line.get("subtype", "unknown")

    hook_infos = None
    raw_hook_infos = line.get("hookInfos", [])
    if raw_hook_infos:
        hook_infos = [
            HookInfo(
                event="",
                name="",
                command=h.get("command"),
            )
            for h in raw_hook_infos
        ]

    system_event_data = SystemEventData(
        subtype=subtype,
        duration_ms=line.get("durationMs"),
        hook_count=line.get("hookCount"),
        hook_infos=hook_infos,
        hook_errors=line.get("hookErrors"),
        prevented_continuation=line.get("preventedContinuation"),
        stop_reason=line.get("stopReason"),
    )

    return [
        NormalizedMessage(
            id=line.get("uuid", f"system-{line_num}"),
            session_id=session_id,
            source="claude_code",
            source_schema_version=1,
            msg_type="system_event",
            timestamp=line.get("timestamp", ""),
            system_event_data=system_event_data,
            raw_file_path=file_path,
            raw_line_number=line_num,
        )
    ]


def _transform_queue_operation(
    line: dict[str, Any],
    session_id: str,
    file_path: str,
    line_num: int,
) -> list[NormalizedMessage]:
    """Transform a Claude Code queue operation message."""
    content = line.get("content", "")

    # Parse task info from content (XML-like format)
    task_id = None
    status = None
    summary = None
    output_file = None

    task_id_match = re.search(r"<task-id>([^<]+)</task-id>", content)
    if task_id_match:
        task_id = task_id_match.group(1)

    status_match = re.search(r"<status>([^<]+)</status>", content)
    if status_match:
        status = status_match.group(1)

    summary_match = re.search(r"<summary>([^<]+)</summary>", content)
    if summary_match:
        summary = summary_match.group(1)

    output_match = re.search(r"<output-file>([^<]+)</output-file>", content)
    if output_match:
        output_file = output_match.group(1)

    queue_data = QueueOperationData(
        operation=line.get("operation", "unknown"),
        task_id=task_id,
        status=status,
        summary=summary,
        output_file=output_file,
    )

    return [
        NormalizedMessage(
            id=f"queue-{task_id or line_num}",
            session_id=session_id,
            source="claude_code",
            source_schema_version=1,
            msg_type="queue_operation",
            timestamp=line.get("timestamp", ""),
            content=content,
            queue_operation_data=queue_data,
            raw_file_path=file_path,
            raw_line_number=line_num,
        )
    ]


def _transform_file_snapshot(
    line: dict[str, Any],
    session_id: str,
    file_path: str,
    line_num: int,
) -> list[NormalizedMessage]:
    """Transform a Claude Code file-history-snapshot message."""
    return [
        NormalizedMessage(
            id=line.get("uuid", f"snapshot-{line_num}"),
            session_id=session_id,
            source="claude_code",
            source_schema_version=1,
            msg_type="file_snapshot",
            timestamp=line.get("timestamp", ""),
            raw_data=line,  # Preserve full snapshot data
            raw_file_path=file_path,
            raw_line_number=line_num,
        )
    ]


def _transform_summary(
    line: dict[str, Any],
    session_id: str,
    file_path: str,
    line_num: int,
) -> list[NormalizedMessage]:
    """Transform a Claude Code summary message."""
    return [
        NormalizedMessage(
            id=line.get("uuid", f"summary-{line_num}"),
            session_id=session_id,
            source="claude_code",
            source_schema_version=1,
            msg_type="summary",
            timestamp=line.get("timestamp", ""),
            content=line.get("summary"),
            raw_data=line,  # Preserve full summary data
            raw_file_path=file_path,
            raw_line_number=line_num,
        )
    ]
