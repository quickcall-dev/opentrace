# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Claude Code Schema v1 - Frozen 2026-02-04.

Location: ~/.claude/projects/{path-encoded-dir}/{session-id}.jsonl
Format: JSONL (one JSON object per line)
Encoding: Path /Users/bob/myproject -> -Users-bob-myproject

DO NOT MODIFY this schema. If Claude Code changes its format,
create a v2.py file instead.

Reference: Based on Claude Code session format analysis.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict


# --- Content Block Types ---


class ClaudeTextBlock(TypedDict):
    """Text content block in assistant message."""

    type: Literal["text"]
    text: str


class ClaudeThinkingBlock(TypedDict, total=False):
    """Thinking/reasoning content block in assistant message.

    Contains the actual thinking text and a cryptographic signature
    for verification.
    """

    type: Literal["thinking"]
    thinking: str
    signature: str  # Cryptographic signature for the thinking content


class ClaudeToolUseBlock(TypedDict):
    """Tool use content block in assistant message."""

    type: Literal["tool_use"]
    id: str
    name: str
    input: dict[str, Any]


class ClaudeToolResultBlock(TypedDict, total=False):
    """Tool result content block in user message."""

    type: Literal["tool_result"]
    tool_use_id: str
    content: str | list[dict[str, Any]]


# Union of all content block types
ClaudeContentBlock = ClaudeTextBlock | ClaudeThinkingBlock | ClaudeToolUseBlock | ClaudeToolResultBlock


# --- Message Inner Types ---


class ClaudeUserMessageContent(TypedDict, total=False):
    """Inner content of a user message."""

    role: Literal["user"]
    content: str | list[ClaudeToolResultBlock]


class ClaudeAssistantMessageContent(TypedDict, total=False):
    """Inner content of an assistant message.

    The 'usage' field is inside message for assistant responses.
    """

    role: Literal["assistant"]
    content: list[ClaudeContentBlock]
    model: str
    id: str  # Message ID (e.g., "msg_01QbK2yT19RF7YvreJX9kBo7")
    type: Literal["message"]
    usage: "ClaudeUsage"
    stop_reason: str | None
    stop_sequence: str | None


# --- Token Usage ---


class ClaudeCacheCreation(TypedDict, total=False):
    """Cache creation token details."""

    ephemeral_5m_input_tokens: int
    ephemeral_1h_input_tokens: int


class ClaudeUsage(TypedDict, total=False):
    """Token usage metrics for assistant messages.

    Located inside message.usage for assistant messages.
    """

    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    cache_creation: ClaudeCacheCreation
    service_tier: str


# --- Thinking Metadata (user message field) ---


class ClaudeThinkingMetadata(TypedDict, total=False):
    """Thinking configuration from user messages."""

    maxThinkingTokens: int
    level: str  # Thinking level setting
    disabled: bool


# --- Top-Level Message Types ---


@dataclass
class ClaudeUserMessage:
    """User message in Claude Code session.

    Full structure based on live session analysis:
    {
      "parentUuid": "...",
      "isSidechain": false,
      "userType": "external",
      "cwd": "/path/to/project",
      "sessionId": "uuid",
      "version": "2.1.31",
      "gitBranch": "main",
      "type": "user",
      "message": { "role": "user", "content": "..." },
      "uuid": "...",
      "timestamp": "2026-02-04T10:00:00.000Z",
      "thinkingMetadata": { "maxThinkingTokens": 31999 },
      "todos": [],
      "permissionMode": "acceptEdits",
      "imagePasteIds": []
    }
    """

    type: Literal["user"]
    uuid: str
    timestamp: str
    message: ClaudeUserMessageContent

    # Threading
    parentUuid: str | None = None
    isSidechain: bool = False

    # Session context
    sessionId: str = ""
    cwd: str | None = None
    version: str | None = None
    gitBranch: str | None = None
    slug: str | None = None
    userType: str = "external"

    # User settings
    thinkingMetadata: ClaudeThinkingMetadata | None = None
    todos: list[dict[str, Any]] = field(default_factory=list)
    permissionMode: str | None = None
    imagePasteIds: list[str] = field(default_factory=list)


@dataclass
class ClaudeAssistantMessage:
    """Assistant message in Claude Code session.

    Full structure based on live session analysis:
    {
      "parentUuid": "...",
      "isSidechain": false,
      "userType": "external",
      "cwd": "/path/to/project",
      "sessionId": "uuid",
      "version": "2.1.31",
      "gitBranch": "main",
      "slug": "ethereal-giggling-crown",
      "message": {
        "model": "claude-sonnet-4-5-20250929",
        "id": "msg_01QbK2yT19RF7YvreJX9kBo7",
        "type": "message",
        "role": "assistant",
        "content": [...],
        "stop_reason": "end_turn",
        "usage": { "input_tokens": ..., "output_tokens": ..., ... }
      },
      "requestId": "req_...",
      "type": "assistant",
      "uuid": "...",
      "timestamp": "2026-02-04T10:00:05.000Z"
    }
    """

    type: Literal["assistant"]
    uuid: str
    timestamp: str
    message: ClaudeAssistantMessageContent

    # Threading
    parentUuid: str | None = None
    isSidechain: bool = False

    # Session context
    sessionId: str = ""
    cwd: str | None = None
    version: str | None = None
    gitBranch: str | None = None
    slug: str | None = None
    userType: str = "external"

    # Request tracking
    requestId: str | None = None


# Union type for all message types we process
ClaudeMessage = ClaudeUserMessage | ClaudeAssistantMessage


# --- Skipped Types ---
# These types exist in the session files but are not transformed:
# - "file-history-snapshot": Internal file tracking
# - "summary": Session summaries
# - "system": System/progress messages
# - "progress": Progress updates (hooks, etc.)
# - "queue-operation": Internal queue operations
