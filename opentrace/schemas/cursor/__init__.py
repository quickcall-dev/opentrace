# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Cursor IDE schema definitions.

This module provides TypedDict schemas for all Cursor data structures
stored in SQLite databases and configuration files, plus transformation
functions to convert Cursor data to the unified NormalizedMessage format.
"""

from .v1 import (
    # Global state (globalStorage/state.vscdb)
    CursorDailyStats,
    CursorPendingMemory,
    CursorServerConfig,
    CursorServerConfigBackground,
    CursorServerConfigChat,
    CursorServerConfigIndexing,
    # Workspace state (workspaceStorage/*/state.vscdb)
    CursorAiServicePrompt,
    CursorComposerData,
    CursorComposerEntry,
    # AI tracking database (ai-code-tracking.db)
    CursorAiCodeHash,
    CursorConversationSummary,
    CursorScoredCommit,
    CursorTrackingState,
    # Workspace mapping
    CursorWorkspaceJson,
    # MCP metadata
    CursorMcpConfig,
    CursorMcpServerConfig,
    CursorMcpServerMetadata,
    CursorMcpTool,
    CursorMcpToolArguments,
    CursorMcpToolOutputSchema,
    # IDE state
    CursorIdeState,
    CursorRecentFile,
    # Agent transcripts (Parser-Agent)
    CursorAgentTranscript,
    CursorTranscriptMessage,
    CursorToolInvocation,
    CursorTerminalSession,
    CursorProject,
)
from .transform import (
    extract_session_id,
    transform_cursor_v1,
    transform_transcript_message,
    transform_tool_invocation,
    transform_composer_metadata,
)
from .v2 import (
    CursorTimingInfo,
    CursorModelConfig,
    CursorVscdbBubble,
    CursorBubbleTokenCount,
    CursorBubbleIdEntry,
    CursorAgentKvToolResult,
)
from .transform_vscdb import transform_cursor_vscdb

__all__ = [
    # Global state
    "CursorDailyStats",
    "CursorPendingMemory",
    "CursorServerConfig",
    "CursorServerConfigChat",
    "CursorServerConfigBackground",
    "CursorServerConfigIndexing",
    # Workspace state
    "CursorComposerData",
    "CursorComposerEntry",
    "CursorAiServicePrompt",
    # AI tracking database
    "CursorAiCodeHash",
    "CursorConversationSummary",
    "CursorScoredCommit",
    "CursorTrackingState",
    # Workspace mapping
    "CursorWorkspaceJson",
    # MCP metadata
    "CursorMcpServerMetadata",
    "CursorMcpTool",
    "CursorMcpToolArguments",
    "CursorMcpToolOutputSchema",
    "CursorMcpConfig",
    "CursorMcpServerConfig",
    # IDE state
    "CursorIdeState",
    "CursorRecentFile",
    # Agent transcripts (Parser-Agent)
    "CursorAgentTranscript",
    "CursorTranscriptMessage",
    "CursorToolInvocation",
    "CursorTerminalSession",
    "CursorProject",
    # Transform functions
    "extract_session_id",
    "transform_cursor_v1",
    "transform_transcript_message",
    "transform_tool_invocation",
    "transform_composer_metadata",
    # V2 cursorDiskKV types
    "CursorTimingInfo",
    "CursorModelConfig",
    "CursorVscdbBubble",
    "CursorBubbleTokenCount",
    "CursorBubbleIdEntry",
    "CursorAgentKvToolResult",
    # V2 transform
    "transform_cursor_vscdb",
]
