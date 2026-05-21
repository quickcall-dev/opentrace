# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Transform Codex CLI v1 session data to unified format."""

import json
import re
from typing import Any

from opentrace.schemas.unified import (
    NormalizedMessage,
    TokenUsage,
    ToolCall,
    ToolResult,
)


def extract_session_id(file_path: str) -> str:
    """Extract session ID from Codex CLI file path.

    Path format: ~/.codex/sessions/YYYY/MM/DD/rollout-{ISO-timestamp}-{uuid}.jsonl
    Example: rollout-2026-02-04T16-44-26-019c285c-569c-7f12-b514-a9ceff5f3f8d.jsonl
    Returns: 019c285c-569c-7f12-b514-a9ceff5f3f8d
    """
    # Try to extract UUID from filename
    # Filename format: rollout-2026-02-04T16-44-26-{uuid}.jsonl
    # The ISO timestamp uses hyphens, so match everything up to the UUID
    match = re.search(r"rollout-.+-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$", file_path)
    if match:
        return match.group(1)

    # Fallback: use filename without extension
    match = re.search(r"/([^/]+)\.jsonl$", file_path)
    if match:
        return match.group(1)

    return file_path


def _make_id(session_id: str, line_num: int, suffix: str = "") -> str:
    """Generate a deterministic ID for messages that don't have one.

    Uses session_id and line_num so reprocessing the same file yields
    identical message IDs, enabling idempotent ingestion.
    """
    base = f"{session_id}-L{line_num}"
    return f"{base}-{suffix}" if suffix else base


class CodexTransformContext:
    """Context for transforming a Codex session.

    Tracks state across lines, particularly for token counts
    which arrive separately from the messages they apply to.
    """

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.cli_version: str | None = None
        self.current_model: str | None = None
        self.last_token_usage: TokenUsage = TokenUsage()
        self.cwd: str | None = None
        self.git_branch: str | None = None
        self.git_commit: str | None = None
        self.repo_url: str | None = None

    def update_from_session_meta(self, payload: dict[str, Any], git: dict[str, Any] | None = None) -> None:
        """Update context from session_meta payload and optional git info."""
        self.session_id = payload.get("id")
        self.cli_version = payload.get("cli_version")
        self.cwd = payload.get("cwd")
        if git:
            self.git_branch = git.get("branch") or self.git_branch
            self.git_commit = git.get("commit_hash") or self.git_commit
            self.repo_url = git.get("repository_url") or self.repo_url

    def update_from_turn_context(self, payload: dict[str, Any]) -> None:
        """Update context from turn_context payload."""
        # Model can be at top level or in collaboration_mode
        self.current_model = payload.get("model")
        if not self.current_model:
            collab = payload.get("collaboration_mode", {})
            self.current_model = collab.get("model")
        self.git_branch = payload.get("branch") or self.git_branch
        self.git_commit = payload.get("commit") or self.git_commit
        self.repo_url = payload.get("repo_url") or self.repo_url

    def update_from_token_count(self, info: dict[str, Any]) -> None:
        """Update context from token_count info."""
        last_usage = info.get("last_token_usage", {})
        self.last_token_usage = TokenUsage(
            input=last_usage.get("input_tokens", 0),
            output=last_usage.get("output_tokens", 0),
            cached=last_usage.get("cached_input_tokens", 0),
            thinking=last_usage.get("reasoning_output_tokens", 0),
        )

    def get_and_reset_tokens(self) -> TokenUsage:
        """Get last token usage and reset it."""
        tokens = self.last_token_usage
        self.last_token_usage = TokenUsage()
        return tokens


def transform_codex_v1(
    line: dict[str, Any],
    file_path: str,
    line_num: int,
    context: CodexTransformContext | None = None,
) -> list[NormalizedMessage]:
    """Transform a Codex CLI JSONL line to normalized messages.

    Args:
        line: Parsed JSON object from a JSONL line
        file_path: Path to the source file
        line_num: Line number in the source file (1-indexed)
        context: Optional transform context for tracking state across lines.
                 If not provided, a new context is created (stateless mode).

    Returns:
        List of NormalizedMessage objects. Usually returns 0 or 1 messages.
        Returns empty list for metadata-only lines (session_meta, turn_context, token_count).
    """
    if context is None:
        context = CodexTransformContext()

    line_type = line.get("type")
    payload = line.get("payload", {})
    session_id = context.session_id or extract_session_id(file_path)

    # Update context from metadata lines
    if line_type == "session_meta":
        context.update_from_session_meta(payload, git=line.get("git"))
        return []

    if line_type == "turn_context":
        context.update_from_turn_context(payload)
        return []

    # Handle event_msg types
    if line_type == "event_msg":
        return _transform_event_msg(
            line, payload, session_id, file_path, line_num, context
        )

    # Handle response_item types
    if line_type == "response_item":
        return _transform_response_item(
            line, payload, session_id, file_path, line_num, context
        )

    return []


def _transform_event_msg(
    line: dict[str, Any],
    payload: dict[str, Any],
    session_id: str,
    file_path: str,
    line_num: int,
    context: CodexTransformContext,
) -> list[NormalizedMessage]:
    """Transform event_msg lines."""
    event_type = payload.get("type")

    if event_type == "token_count":
        # Update context with token info, don't produce a message
        # Note: info can be null at session start
        info = payload.get("info")
        if info:
            context.update_from_token_count(info)
        return []

    if event_type == "turn_aborted":
        # Turn was interrupted by user
        return [
            NormalizedMessage(
                id=_make_id(session_id, line_num, "aborted"),
                session_id=session_id,
                source="codex_cli",
                source_schema_version=1,
                msg_type="info",
                timestamp=line.get("timestamp", ""),
                content=f"Turn aborted: {payload.get('reason', 'unknown')}",
                raw_file_path=file_path,
                raw_line_number=line_num,
            )
        ]

    if event_type == "user_message":
        return [
            NormalizedMessage(
                id=_make_id(session_id, line_num, "user"),
                session_id=session_id,
                source="codex_cli",
                source_schema_version=1,
                msg_type="user",
                timestamp=line.get("timestamp", ""),
                content=payload.get("message", ""),
                raw_file_path=file_path,
                raw_line_number=line_num,
            )
        ]

    if event_type == "agent_message":
        return [
            NormalizedMessage(
                id=_make_id(session_id, line_num, "agent"),
                session_id=session_id,
                source="codex_cli",
                source_schema_version=1,
                msg_type="assistant",
                timestamp=line.get("timestamp", ""),
                content=payload.get("message", ""),
                model=context.current_model,
                raw_file_path=file_path,
                raw_line_number=line_num,
            )
        ]

    if event_type == "error":
        return [
            NormalizedMessage(
                id=_make_id(session_id, line_num, "error"),
                session_id=session_id,
                source="codex_cli",
                source_schema_version=1,
                msg_type="error",
                timestamp=line.get("timestamp", ""),
                content=payload.get("message", ""),
                raw_data=payload.get("codex_error_info"),
                raw_file_path=file_path,
                raw_line_number=line_num,
            )
        ]

    # Skip high-frequency delta/streaming events that add noise without value
    _SKIP_EVENTS = {
        "agent_message_delta", "agent_reasoning_delta",
        "agent_reasoning_raw_content_delta", "reasoning_content_delta",
        "reasoning_raw_content_delta", "exec_command_output_delta",
        "agent_message_content_delta",
    }
    if event_type in _SKIP_EVENTS:
        return []

    # Capture other event types as info messages with raw_data for observability
    if event_type:
        return [
            NormalizedMessage(
                id=_make_id(session_id, line_num, event_type),
                session_id=session_id,
                source="codex_cli",
                source_schema_version=1,
                msg_type="info",
                timestamp=line.get("timestamp", ""),
                content=f"Event: {event_type}",
                raw_data=payload,
                raw_file_path=file_path,
                raw_line_number=line_num,
            )
        ]

    return []


def _transform_response_item(
    line: dict[str, Any],
    payload: dict[str, Any],
    session_id: str,
    file_path: str,
    line_num: int,
    context: CodexTransformContext,
) -> list[NormalizedMessage]:
    """Transform response_item lines."""
    item_type = payload.get("type")

    if item_type == "message":
        return _transform_message_item(
            line, payload, session_id, file_path, line_num, context
        )

    if item_type == "reasoning":
        # Reasoning is usually encrypted, we just note it exists
        return [
            NormalizedMessage(
                id=_make_id(session_id, line_num, "reasoning"),
                session_id=session_id,
                source="codex_cli",
                source_schema_version=1,
                msg_type="assistant",
                timestamp=line.get("timestamp", ""),
                content=None,
                thinking="[encrypted]" if payload.get("encrypted_content") else None,
                model=context.current_model,
                raw_file_path=file_path,
                raw_line_number=line_num,
            )
        ]

    if item_type == "function_call":
        # Parse arguments from JSON string
        args_str = payload.get("arguments", "{}")
        try:
            args = json.loads(args_str)
        except json.JSONDecodeError:
            args = {"raw": args_str}

        return [
            NormalizedMessage(
                id=payload.get("call_id", _make_id(session_id, line_num, "call")),
                session_id=session_id,
                source="codex_cli",
                source_schema_version=1,
                msg_type="tool_call",
                timestamp=line.get("timestamp", ""),
                content=None,
                tokens=context.get_and_reset_tokens(),
                tool_call=ToolCall(
                    id=payload.get("call_id", ""),
                    name=payload.get("name", ""),
                    input=args,
                ),
                model=context.current_model,
                raw_file_path=file_path,
                raw_line_number=line_num,
            )
        ]

    if item_type == "function_call_output":
        raw_output = payload.get("output", "")

        # output is a JSON-encoded string; parse it to extract inner fields
        output = raw_output
        status: str = "success"
        try:
            parsed = json.loads(raw_output)
            if isinstance(parsed, dict):
                inner = parsed.get("output", raw_output)
                output = inner if isinstance(inner, str) else json.dumps(inner)
                # Use the explicit success field if available
                if "success" in parsed:
                    status = "success" if parsed["success"] else "failure"
        except (json.JSONDecodeError, TypeError):
            pass

        return [
            NormalizedMessage(
                id=f"{payload.get('call_id', '')}-result",
                session_id=session_id,
                source="codex_cli",
                source_schema_version=1,
                msg_type="tool_result",
                timestamp=line.get("timestamp", ""),
                content=None,
                tool_result=ToolResult(
                    call_id=payload.get("call_id", ""),
                    output=output,
                    status=status,
                ),
                raw_file_path=file_path,
                raw_line_number=line_num,
            )
        ]

    return []


def _transform_message_item(
    line: dict[str, Any],
    payload: dict[str, Any],
    session_id: str,
    file_path: str,
    line_num: int,
    context: CodexTransformContext,
) -> list[NormalizedMessage]:
    """Transform response_item with type=message."""
    role = payload.get("role")
    content_blocks = payload.get("content", [])

    # Extract text from content blocks
    text_parts = []
    for block in content_blocks:
        if isinstance(block, dict):
            if block.get("type") in ("input_text", "output_text"):
                text_parts.append(block.get("text", ""))

    content = "\n".join(text_parts) if text_parts else None

    # Map role to message type
    if role == "developer":
        msg_type = "system"
    elif role == "user":
        msg_type = "user"
    elif role == "assistant":
        msg_type = "assistant"
    else:
        msg_type = "assistant"  # Default

    return [
        NormalizedMessage(
            id=_make_id(session_id, line_num, "msg"),
            session_id=session_id,
            source="codex_cli",
            source_schema_version=1,
            msg_type=msg_type,
            timestamp=line.get("timestamp", ""),
            content=content,
            tokens=context.get_and_reset_tokens()
            if msg_type == "assistant"
            else TokenUsage(),
            model=context.current_model if msg_type == "assistant" else None,
            raw_file_path=file_path,
            raw_line_number=line_num,
        )
    ]
