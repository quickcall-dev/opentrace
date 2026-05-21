# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Gemini CLI Schema v1 - Frozen 2026-02-04.

Official Source: https://github.com/google-gemini/gemini-cli
Schema Files:
  - packages/core/src/services/chatRecordingService.ts (ConversationRecord, MessageRecord, etc.)
  - packages/core/src/tools/tools.ts (ToolResultDisplay, FileDiff, TodoList, etc.)
  - packages/core/src/utils/terminalSerializer.ts (AnsiOutput, AnsiLine, AnsiToken)
  - packages/core/src/utils/thoughtUtils.ts (ThoughtSummary)
  - packages/core/src/core/coreToolScheduler.ts (Status)

CLI Version: Latest from https://github.com/google-gemini/gemini-cli
Location: ~/.gemini/tmp/{project_hash}/chats/session-{timestamp}-{id}.json
Format: Single JSON file (NOT JSONL)
Project Hash: SHA-256 of project path

DO NOT MODIFY this schema. If Gemini CLI changes its format,
create a v2.py file instead.
"""

from typing import Any, Literal, TypedDict


# =============================================================================
# ENUMS AND CONSTANTS
# =============================================================================


# Tool status values (coreToolScheduler.ts)
GeminiToolStatus = Literal[
    "validating",
    "scheduled",
    "executing",
    "awaiting_approval",
    "success",
    "error",
    "cancelled",
]

# Message types (chatRecordingService.ts:73-76)
GeminiMessageType = Literal["user", "gemini", "info", "error", "warning"]

# Todo status values (tools.ts:653)
GeminiTodoStatus = Literal["pending", "in_progress", "completed", "cancelled"]


# =============================================================================
# ANSI OUTPUT TYPES (terminalSerializer.ts:8-20)
# For shell command output with terminal formatting
# =============================================================================


class GeminiAnsiToken(TypedDict, total=False):
    """ANSI token with text and formatting (terminalSerializer.ts:8-17).

    Represents a styled segment of terminal output with ANSI escape codes.
    """

    text: str
    bold: bool
    italic: bool
    underline: bool
    dim: bool
    inverse: bool
    fg: str  # Foreground color (e.g., "#ffffff" or "default")
    bg: str  # Background color


# AnsiLine is a list of AnsiTokens (terminalSerializer.ts:19)
GeminiAnsiLine = list[GeminiAnsiToken]

# AnsiOutput is a list of AnsiLines (terminalSerializer.ts:20)
GeminiAnsiOutput = list[GeminiAnsiLine]


# =============================================================================
# DIFF STAT TYPES (tools.ts:670-679)
# =============================================================================


class GeminiDiffStat(TypedDict, total=False):
    """Diff statistics for file changes (tools.ts:670-679).

    Tracks lines/chars added/removed by model and user.
    """

    model_added_lines: int
    model_removed_lines: int
    model_added_chars: int
    model_removed_chars: int
    user_added_lines: int
    user_removed_lines: int
    user_added_chars: int
    user_removed_chars: int


# =============================================================================
# FILE DIFF TYPES (tools.ts:660-668)
# =============================================================================


class GeminiFileDiff(TypedDict, total=False):
    """File diff result display (tools.ts:660-668).

    Represents changes to a file with full diff information.
    """

    fileDiff: str  # Unified diff format
    fileName: str
    filePath: str
    originalContent: str | None
    newContent: str
    diffStat: GeminiDiffStat
    isNewFile: bool


# =============================================================================
# TODO LIST TYPES (tools.ts:647-658)
# =============================================================================


class GeminiTodo(TypedDict):
    """Todo item (tools.ts:655-658)."""

    description: str
    status: GeminiTodoStatus


class GeminiTodoList(TypedDict):
    """Todo list result display (tools.ts:647-649)."""

    todos: list[GeminiTodo]


# =============================================================================
# TOOL RESULT DISPLAY (tools.ts:651)
# Union of all result display types
# =============================================================================

# ToolResultDisplay = string | FileDiff | AnsiOutput | TodoList
GeminiToolResultDisplay = str | GeminiFileDiff | GeminiAnsiOutput | GeminiTodoList


# =============================================================================
# TOKEN USAGE (chatRecordingService.ts:34-41)
# =============================================================================


class GeminiTokensSummary(TypedDict, total=False):
    """Token usage summary (chatRecordingService.ts:34-41).

    Maps to GenerateContentResponseUsageMetadata fields.
    """

    input: int  # promptTokenCount
    output: int  # candidatesTokenCount
    cached: int  # cachedContentTokenCount
    thoughts: int  # thoughtsTokenCount
    tool: int  # toolUsePromptTokenCount
    total: int  # totalTokenCount




# =============================================================================
# THOUGHT TYPES (thoughtUtils.ts + chatRecordingService.ts)
# =============================================================================


class GeminiThoughtSummary(TypedDict, total=False):
    """Thought summary from reasoning (thoughtUtils.ts).

    Contains the model's reasoning/thinking content.
    """

    subject: str  # Bold header, e.g., "Planning Architecture"
    description: str  # Detailed reasoning text


class GeminiTimestampedThought(TypedDict, total=False):
    """Thought with timestamp (chatRecordingService.ts:80).

    ThoughtSummary with timestamp for recording.
    """

    subject: str
    description: str
    timestamp: str  # ISO timestamp




# =============================================================================
# FUNCTION RESPONSE TYPES (for tool results)
# =============================================================================


class GeminiFunctionResponseData(TypedDict, total=False):
    """Response data from function execution."""

    output: str
    error: str


class GeminiFunctionResponse(TypedDict, total=False):
    """Function response inside tool result."""

    id: str
    name: str
    response: GeminiFunctionResponseData


class GeminiToolResultItem(TypedDict, total=False):
    """Individual item in tool result list (PartListUnion)."""

    functionResponse: GeminiFunctionResponse


# =============================================================================
# TOOL CALL ARGS (various tool argument structures)
# =============================================================================


class GeminiWriteFileArgs(TypedDict, total=False):
    """Arguments for write_file tool."""

    file_path: str
    content: str


class GeminiEditArgs(TypedDict, total=False):
    """Arguments for edit tool."""

    file_path: str
    instruction: str
    old_string: str
    new_string: str


class GeminiShellArgs(TypedDict, total=False):
    """Arguments for run_shell_command tool."""

    command: str


class GeminiWriteTodosArgs(TypedDict, total=False):
    """Arguments for write_todos tool."""

    todos: list[GeminiTodo]


class GeminiGlobArgs(TypedDict, total=False):
    """Arguments for glob tool."""

    pattern: str
    path: str


class GeminiGrepArgs(TypedDict, total=False):
    """Arguments for grep tool."""

    pattern: str
    path: str
    include: str


class GeminiReadFileArgs(TypedDict, total=False):
    """Arguments for read_file tool."""

    file_path: str
    offset: int
    limit: int


class GeminiListDirArgs(TypedDict, total=False):
    """Arguments for list_dir tool."""

    path: str
    depth: int


# Union of all tool argument types
GeminiToolCallArgs = (
    GeminiWriteFileArgs
    | GeminiEditArgs
    | GeminiShellArgs
    | GeminiWriteTodosArgs
    | GeminiGlobArgs
    | GeminiGrepArgs
    | GeminiReadFileArgs
    | GeminiListDirArgs
    | dict[str, Any]  # Fallback for unknown tools
)


# =============================================================================
# TOOL CALL RECORD (chatRecordingService.ts:56-68)
# =============================================================================


class GeminiToolCallRecord(TypedDict, total=False):
    """Tool call record (chatRecordingService.ts:56-68).

    Complete record of a tool execution within a conversation.
    """

    id: str
    name: str  # e.g., "write_file", "run_shell_command", "edit"
    args: GeminiToolCallArgs
    result: list[GeminiToolResultItem] | None  # PartListUnion
    status: GeminiToolStatus
    timestamp: str  # ISO timestamp

    # UI-specific fields for display purposes
    displayName: str  # e.g., "WriteFile", "Shell", "Edit"
    description: str
    resultDisplay: GeminiToolResultDisplay
    renderOutputAsMarkdown: bool




# =============================================================================
# MESSAGE TYPES (chatRecordingService.ts:46-88)
# =============================================================================


class GeminiUserMessageRecord(TypedDict, total=False):
    """User message record (chatRecordingService.ts:73-76).

    User input message in conversation.
    """

    id: str
    timestamp: str
    type: Literal["user"]
    content: str | Any  # Can be string or PartListUnion
    displayContent: Any


class GeminiInfoMessageRecord(TypedDict, total=False):
    """Info message record (chatRecordingService.ts:73-76).

    Informational system message.
    """

    id: str
    timestamp: str
    type: Literal["info"]
    content: str | Any
    displayContent: Any


class GeminiErrorMessageRecord(TypedDict, total=False):
    """Error message record (chatRecordingService.ts:73-76).

    Error message in conversation.
    """

    id: str
    timestamp: str
    type: Literal["error"]
    content: str | Any
    displayContent: Any


class GeminiWarningMessageRecord(TypedDict, total=False):
    """Warning message record (chatRecordingService.ts:73-76).

    Warning message in conversation.
    """

    id: str
    timestamp: str
    type: Literal["warning"]
    content: str | Any
    displayContent: Any


class GeminiGeminiMessageRecord(TypedDict, total=False):
    """Gemini (assistant) message record (chatRecordingService.ts:78-83).

    Assistant response with tool calls, thoughts, and token usage.
    """

    id: str
    timestamp: str
    type: Literal["gemini"]
    content: str | Any  # PartListUnion
    displayContent: Any

    # Gemini-specific fields
    toolCalls: list[GeminiToolCallRecord]
    thoughts: list[GeminiTimestampedThought]
    tokens: GeminiTokensSummary | None
    model: str  # e.g., "gemini-2.5-pro"


# Union of all message types (chatRecordingService.ts:88)
GeminiMessageRecord = (
    GeminiUserMessageRecord
    | GeminiGeminiMessageRecord
    | GeminiInfoMessageRecord
    | GeminiErrorMessageRecord
    | GeminiWarningMessageRecord
)


# =============================================================================
# CONVERSATION RECORD (chatRecordingService.ts:93-102)
# =============================================================================


class GeminiConversationRecord(TypedDict, total=False):
    """Complete conversation record (chatRecordingService.ts:93-102).

    Top-level structure stored in session files.
    """

    sessionId: str  # UUID
    projectHash: str  # SHA-256 of project root path
    startTime: str  # ISO timestamp
    lastUpdated: str  # ISO timestamp
    messages: list[GeminiMessageRecord]
    summary: str  # Optional session summary
    directories: list[str]  # Workspace dirs added via /dir add


# =============================================================================
# RESUMED SESSION (chatRecordingService.ts:107-110)
# =============================================================================


class GeminiResumedSessionData(TypedDict, total=False):
    """Resumed session data (chatRecordingService.ts:107-110).

    Data structure for resuming an existing session.
    """

    conversation: GeminiConversationRecord
    filePath: str


# =============================================================================
# TOOL CONFIRMATION TYPES (tools.ts)
# =============================================================================


GeminiToolConfirmationOutcome = Literal["approved", "rejected", "edited"]


class GeminiToolEditConfirmationDetails(TypedDict, total=False):
    """Tool edit confirmation details (tools.ts:681-691)."""

    type: Literal["edit"]
    title: str
    fileName: str
    filePath: str
    fileDiff: str


class GeminiToolShellConfirmationDetails(TypedDict, total=False):
    """Tool shell confirmation details."""

    type: Literal["shell"]
    title: str
    command: str


class GeminiToolWriteConfirmationDetails(TypedDict, total=False):
    """Tool write confirmation details."""

    type: Literal["write"]
    title: str
    fileName: str
    filePath: str


GeminiToolConfirmationDetails = (
    GeminiToolEditConfirmationDetails
    | GeminiToolShellConfirmationDetails
    | GeminiToolWriteConfirmationDetails
)


