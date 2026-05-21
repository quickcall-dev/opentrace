# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Transform Gemini CLI v1 session data to unified format."""

from typing import Any

from opentrace.schemas.unified import (
    NormalizedMessage,
    TokenUsage,
    ToolCall,
    ToolResult,
)


def extract_tokens(tokens: dict[str, Any] | None) -> TokenUsage:
    """Extract token usage from Gemini tokens dict."""
    if not tokens:
        return TokenUsage()

    return TokenUsage(
        input=tokens.get("input", 0),
        output=tokens.get("output", 0),
        cached=tokens.get("cached", 0),
        thinking=tokens.get("thoughts", 0),
    )


def extract_thoughts(thoughts: list[dict[str, Any]]) -> str | None:
    """Extract and combine thought descriptions."""
    if not thoughts:
        return None

    # Combine all thoughts with their subjects
    parts = []
    for thought in thoughts:
        subject = thought.get("subject", "")
        description = thought.get("description", "")
        if subject and description:
            parts.append(f"**{subject}**: {description}")
        elif description:
            parts.append(description)
        elif subject:
            parts.append(subject)

    return "\n\n".join(parts) if parts else None


def transform_gemini_v1(
    session: dict[str, Any],
    file_path: str,
) -> list[NormalizedMessage]:
    """Transform a Gemini CLI session file to normalized messages.

    Args:
        session: Parsed JSON session object
        file_path: Path to the source file

    Returns:
        List of NormalizedMessage objects for all messages in the session.
    """
    session_id = session.get("sessionId", "")
    messages = session.get("messages", [])

    normalized = []
    for msg in messages:
        normalized.extend(_transform_message(msg, session_id, file_path))

    return normalized


def _transform_message(
    msg: dict[str, Any],
    session_id: str,
    file_path: str,
) -> list[NormalizedMessage]:
    """Transform a single Gemini message.

    May return multiple NormalizedMessages if the message contains tool calls.
    """
    msg_type = msg.get("type")

    if msg_type == "user":
        return [_transform_user_message(msg, session_id, file_path)]
    elif msg_type == "gemini":
        return _transform_gemini_message(msg, session_id, file_path)
    elif msg_type == "error":
        return [_transform_error_message(msg, session_id, file_path)]
    elif msg_type == "info":
        return [_transform_info_message(msg, session_id, file_path)]
    elif msg_type == "warning":
        return [_transform_warning_message(msg, session_id, file_path)]

    return []


def _transform_user_message(
    msg: dict[str, Any],
    session_id: str,
    file_path: str,
) -> NormalizedMessage:
    """Transform a user message."""
    return NormalizedMessage(
        id=msg.get("id", ""),
        session_id=session_id,
        source="gemini_cli",
        source_schema_version=1,
        msg_type="user",
        timestamp=msg.get("timestamp", ""),
        content=msg.get("content"),
        raw_file_path=file_path,
    )


def _transform_gemini_message(
    msg: dict[str, Any],
    session_id: str,
    file_path: str,
) -> list[NormalizedMessage]:
    """Transform a Gemini (assistant) message.

    Returns the main assistant message plus separate messages for each tool call/result.
    """
    messages = []

    tokens = extract_tokens(msg.get("tokens"))
    thinking = extract_thoughts(msg.get("thoughts", []))

    # Main assistant message
    messages.append(
        NormalizedMessage(
            id=msg.get("id", ""),
            session_id=session_id,
            source="gemini_cli",
            source_schema_version=1,
            msg_type="assistant",
            timestamp=msg.get("timestamp", ""),
            content=msg.get("content"),
            tokens=tokens,
            thinking=thinking,
            model=msg.get("model"),
            raw_file_path=file_path,
        )
    )

    # Tool calls and results are embedded in the message
    tool_calls = msg.get("toolCalls", [])
    for tc in tool_calls:
        # Tool call
        messages.append(
            NormalizedMessage(
                id=tc.get("id", ""),
                session_id=session_id,
                source="gemini_cli",
                source_schema_version=1,
                msg_type="tool_call",
                timestamp=tc.get("timestamp", msg.get("timestamp", "")),
                content=None,
                tool_call=ToolCall(
                    id=tc.get("id", ""),
                    name=tc.get("name", ""),
                    input=tc.get("args", {}),
                ),
                raw_file_path=file_path,
            )
        )

        # Tool result (if present)
        result = tc.get("result", [])
        result_display = tc.get("resultDisplay")
        status = tc.get("status", "success")

        if result or result_display:
            # Extract output from result or resultDisplay
            output = ""

            # resultDisplay can be a string or a dict
            if isinstance(result_display, str):
                output = result_display
            elif isinstance(result_display, dict):
                # Check for output, error, or file content
                output = (
                    result_display.get("output", "")
                    or result_display.get("error", "")
                    or result_display.get("newContent", "")
                )

            # If no output from resultDisplay, try functionResponse
            if not output and result:
                for r in result:
                    if isinstance(r, dict):
                        func_resp = r.get("functionResponse", {})
                        resp = func_resp.get("response", {})
                        if "output" in resp:
                            output = resp["output"]
                            break
                        elif "error" in resp:
                            output = resp["error"]
                            break

            # Map status: "error" and "cancelled" -> "failure"
            normalized_status = "failure" if status in ("error", "cancelled") else "success"

            messages.append(
                NormalizedMessage(
                    id=f"{tc.get('id', '')}-result",
                    session_id=session_id,
                    source="gemini_cli",
                    source_schema_version=1,
                    msg_type="tool_result",
                    timestamp=tc.get("timestamp", msg.get("timestamp", "")),
                    content=None,
                    tool_result=ToolResult(
                        call_id=tc.get("id", ""),
                        output=str(output),
                        status=normalized_status,
                    ),
                    raw_file_path=file_path,
                )
            )

    return messages


def _transform_error_message(
    msg: dict[str, Any],
    session_id: str,
    file_path: str,
) -> NormalizedMessage:
    """Transform an error message."""
    return NormalizedMessage(
        id=msg.get("id", ""),
        session_id=session_id,
        source="gemini_cli",
        source_schema_version=1,
        msg_type="error",
        timestamp=msg.get("timestamp", ""),
        content=msg.get("content"),
        raw_file_path=file_path,
    )


def _transform_info_message(
    msg: dict[str, Any],
    session_id: str,
    file_path: str,
) -> NormalizedMessage:
    """Transform an info message."""
    return NormalizedMessage(
        id=msg.get("id", ""),
        session_id=session_id,
        source="gemini_cli",
        source_schema_version=1,
        msg_type="info",
        timestamp=msg.get("timestamp", ""),
        content=msg.get("content"),
        raw_file_path=file_path,
    )


def _transform_warning_message(
    msg: dict[str, Any],
    session_id: str,
    file_path: str,
) -> NormalizedMessage:
    """Transform a warning message."""
    return NormalizedMessage(
        id=msg.get("id", ""),
        session_id=session_id,
        source="gemini_cli",
        source_schema_version=1,
        msg_type="info",  # Map to info since unified schema has no "warning" type
        timestamp=msg.get("timestamp", ""),
        content=msg.get("content"),
        raw_file_path=file_path,
    )
