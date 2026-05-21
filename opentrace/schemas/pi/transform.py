# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Transform pi.dev JSONL session data to unified format.

Pi.dev writes append-only JSONL files where each line is a typed event.
Events form a singly-linked list via parentId. Session identity comes from
the first `session` event.

Event types:
  session              → metadata (skip)
  model_change         → track current model/provider
  thinking_level_change → metadata (skip)
  message + role:user  → msg_type="user"
  message + role:assistant → msg_type="assistant" (+ tool_call sub-messages)
  message + role:toolResult → msg_type="tool_result"
  message + role:bashExecution → skip (duplicates tool results)
  custom               → skip
  custom_message       → skip (subagent results, noise)
  compaction           → msg_type="compaction"
"""

from typing import Any

from opentrace.schemas.unified import (
    NormalizedMessage,
    TokenUsage,
    ToolCall,
    ToolResult,
)


def _extract_text(content: list[dict]) -> str:
    """Extract text from pi content parts."""
    texts = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            texts.append(part.get("text", ""))
    return "\n\n".join(texts) if texts else ""


def _extract_thinking(content: list[dict]) -> str:
    """Extract thinking blocks from pi content parts."""
    thoughts = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "thinking":
            thoughts.append(part.get("thinking", ""))
    return "\n\n".join(thoughts) if thoughts else ""


def _extract_tool_calls(
    content: list[dict],
    parent_id: str,
    session_id: str,
    timestamp: str,
    file_path: str,
    line_num: int,
    model: str | None,
) -> list[NormalizedMessage]:
    """Extract tool_call messages from assistant content parts."""
    messages = []
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "toolCall":
            continue
        messages.append(
            NormalizedMessage(
                id=part.get("id", f"{parent_id}-tool"),
                session_id=session_id,
                source="pi",
                source_schema_version=1,
                msg_type="tool_call",
                timestamp=timestamp,
                content=None,
                tool_call=ToolCall(
                    id=part.get("id", ""),
                    name=part.get("name", ""),
                    input=part.get("arguments", {}),
                ),
                model=model,
                raw_file_path=file_path,
                raw_line_number=line_num,
            )
        )
    return messages


def _extract_tokens(usage: dict[str, Any]) -> TokenUsage:
    """Extract token usage from pi assistant message usage dict."""
    return TokenUsage(
        input=usage.get("input", 0),
        output=usage.get("output", 0),
        cached=usage.get("cacheRead", 0),
        thinking=usage.get("cacheWrite", 0),
    )


def transform_pi_v1(
    event: dict[str, Any],
    session_id: str,
    file_path: str,
    line_num: int,
    current_model: str | None = None,
) -> list[NormalizedMessage]:
    """Transform a single pi.dev JSONL event to normalized messages.

    Args:
        event: Parsed JSON object from a JSONL line.
        session_id: Session identifier (from the session event).
        file_path: Path to the source file.
        line_num: Line number in the source file (1-indexed).
        current_model: Current model from the most recent model_change event.

    Returns:
        List of NormalizedMessage objects. May return multiple messages
        for assistant events that contain both text and tool calls.
    """
    event_type = event.get("type")
    event_id = event.get("id", f"evt-{line_num}")
    timestamp = event.get("timestamp", "")

    # Skip metadata-only events
    if event_type in ("session", "thinking_level_change", "custom", "custom_message"):
        return []

    if event_type == "compaction":
        return [
            NormalizedMessage(
                id=event_id,
                session_id=session_id,
                source="pi",
                source_schema_version=1,
                msg_type="compaction",
                timestamp=timestamp,
                content=event.get("summary"),
                raw_data=event,
                raw_file_path=file_path,
                raw_line_number=line_num,
            )
        ]

    if event_type != "message":
        return []

    msg = event.get("message", {})
    role = msg.get("role")

    # User message
    if role == "user":
        content = msg.get("content", [])
        text = _extract_text(content) if isinstance(content, list) else str(content)
        return [
            NormalizedMessage(
                id=event_id,
                session_id=session_id,
                source="pi",
                source_schema_version=1,
                msg_type="user",
                timestamp=timestamp,
                content=text or None,
                raw_file_path=file_path,
                raw_line_number=line_num,
            )
        ]

    # Assistant message
    if role == "assistant":
        content = msg.get("content", [])
        text = _extract_text(content) if isinstance(content, list) else None
        thinking = _extract_thinking(content) if isinstance(content, list) else None
        usage = msg.get("usage", {})
        tokens = _extract_tokens(usage) if usage else TokenUsage()
        model = msg.get("model") or current_model

        messages: list[NormalizedMessage] = []

        # Tool calls from content parts
        if isinstance(content, list):
            tool_calls = _extract_tool_calls(
                content, event_id, session_id, timestamp,
                file_path, line_num, model,
            )
            messages.extend(tool_calls)

        # Assistant message with text + thinking
        if text or thinking:
            messages.insert(
                0,
                NormalizedMessage(
                    id=event_id,
                    session_id=session_id,
                    source="pi",
                    source_schema_version=1,
                    msg_type="assistant",
                    timestamp=timestamp,
                    content=text or None,
                    tokens=tokens,
                    thinking=thinking or None,
                    model=model,
                    raw_file_path=file_path,
                    raw_line_number=line_num,
                ),
            )

        return messages

    # Tool result
    if role == "toolResult":
        content = msg.get("content", [])
        text = _extract_text(content) if isinstance(content, list) else str(content)
        status = "failure" if msg.get("isError") else "success"
        return [
            NormalizedMessage(
                id=event_id,
                session_id=session_id,
                source="pi",
                source_schema_version=1,
                msg_type="tool_result",
                timestamp=timestamp,
                content=None,
                tool_result=ToolResult(
                    call_id=msg.get("toolCallId", ""),
                    output=text,
                    status=status,
                ),
                raw_file_path=file_path,
                raw_line_number=line_num,
            )
        ]

    # Bash execution — skip (duplicates bash tool results)
    if role == "bashExecution":
        return []

    return []
