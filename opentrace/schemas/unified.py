# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Unified schema that all CLI formats transform into.

This is the target format for normalization. All source-specific
schemas transform their data into NormalizedMessage instances.
"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class TokenUsage:
    """Unified token usage metrics."""

    input: int = 0
    output: int = 0
    cached: int = 0
    thinking: int = 0


@dataclass
class ToolCall:
    """Normalized tool call information."""

    id: str
    name: str
    input: dict


@dataclass
class ToolResult:
    """Normalized tool result information."""

    call_id: str
    output: str
    status: Literal["success", "failure"]


@dataclass
class HookInfo:
    """Information about a hook execution."""

    event: str  # e.g., "PostToolUse", "PreToolUse"
    name: str  # e.g., "PostToolUse:Write"
    command: str | None = None
    tool_use_id: str | None = None


@dataclass
class ProgressData:
    """Data for progress events."""

    progress_type: str  # e.g., "hook_progress", "bash_progress"
    hook_info: HookInfo | None = None
    # For bash_progress
    stdout: str | None = None
    stderr: str | None = None


@dataclass
class SystemEventData:
    """Data for system events."""

    subtype: str  # e.g., "turn_duration", "stop_hook_summary", "local_command"
    duration_ms: int | None = None
    hook_count: int | None = None
    hook_infos: list[HookInfo] | None = None
    hook_errors: list[str] | None = None
    prevented_continuation: bool | None = None
    stop_reason: str | None = None


@dataclass
class QueueOperationData:
    """Data for queue/background task operations."""

    operation: str  # e.g., "enqueue", "dequeue"
    task_id: str | None = None
    status: str | None = None
    summary: str | None = None
    output_file: str | None = None


MessageType = Literal[
    # Conversation
    "user",
    "assistant",
    "system",
    "tool_call",
    "tool_result",
    "info",
    "error",
    # Observability
    "progress",
    "system_event",
    "queue_operation",
    "file_snapshot",
    "summary",
]

SourceType = Literal["claude_code", "codex_cli", "gemini_cli", "cursor", "cursor_vscdb", "pi"]


@dataclass
class SessionContext:
    """Per-session context: who is working and on what repo."""

    user_email: str | None = None
    user_name: str | None = None
    device_name: str | None = None
    device_id: str | None = None
    cwd: str | None = None
    repo_url: str | None = None
    repo_name: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    project_hash: str | None = None
    org: str | None = None


@dataclass
class NormalizedMessage:
    """Unified message format that all CLI sources transform into.

    This schema represents the normalized view of messages from any
    supported CLI tool. Raw data is never modified; this is purely
    a transformation layer for unified querying and display.

    Message categories:
    - Conversation: user, assistant, system, tool_call, tool_result, info, error
    - Observability: progress, system_event, queue_operation, file_snapshot, summary
    """

    # Identity
    id: str
    session_id: str
    source: SourceType
    source_schema_version: int

    # Classification
    msg_type: MessageType
    timestamp: str  # ISO 8601

    # Content (for conversation messages)
    content: str | None = None

    # Token metrics (unified names)
    tokens: TokenUsage = field(default_factory=TokenUsage)

    # Tool usage (if applicable)
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None

    # Thinking/reasoning (if available)
    thinking: str | None = None

    # Model (if available)
    model: str | None = None

    # Observability data (for non-conversation messages)
    progress_data: ProgressData | None = None
    system_event_data: SystemEventData | None = None
    queue_operation_data: QueueOperationData | None = None

    # Raw data for passthrough (file_snapshot, summary, or unknown types)
    raw_data: dict[str, Any] | None = None

    # Session context (who + what repo)
    session_context: SessionContext | None = None

    # Raw data reference (for preservation)
    raw_file_path: str = ""
    raw_line_number: int | None = None
