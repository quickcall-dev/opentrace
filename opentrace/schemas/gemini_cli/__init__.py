# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Gemini CLI schema definitions and transformations."""

from opentrace.schemas.gemini_cli.v1 import (
    # Top-level types
    GeminiConversationRecord,
    GeminiResumedSessionData,
    # Message types
    GeminiMessageRecord,
    GeminiUserMessageRecord,
    GeminiGeminiMessageRecord,
    GeminiInfoMessageRecord,
    GeminiErrorMessageRecord,
    GeminiWarningMessageRecord,
    # Tool types
    GeminiToolCallRecord,
    GeminiToolStatus,
    # Tool result display types
    GeminiToolResultDisplay,
    GeminiFileDiff,
    GeminiAnsiOutput,
    GeminiAnsiLine,
    GeminiAnsiToken,
    GeminiTodoList,
    GeminiTodo,
    GeminiTodoStatus,
    GeminiDiffStat,
    # Token types
    GeminiTokensSummary,
    # Thought types
    GeminiThoughtSummary,
    GeminiTimestampedThought,
    # Tool args
    GeminiToolCallArgs,
    GeminiWriteFileArgs,
    GeminiEditArgs,
    GeminiShellArgs,
)
from opentrace.schemas.gemini_cli.transform import transform_gemini_v1

__all__ = [
    # Top-level types
    "GeminiConversationRecord",
    "GeminiResumedSessionData",
    # Message types
    "GeminiMessageRecord",
    "GeminiUserMessageRecord",
    "GeminiGeminiMessageRecord",
    "GeminiInfoMessageRecord",
    "GeminiErrorMessageRecord",
    "GeminiWarningMessageRecord",
    # Tool types
    "GeminiToolCallRecord",
    "GeminiToolStatus",
    # Tool result display types
    "GeminiToolResultDisplay",
    "GeminiFileDiff",
    "GeminiAnsiOutput",
    "GeminiAnsiLine",
    "GeminiAnsiToken",
    "GeminiTodoList",
    "GeminiTodo",
    "GeminiTodoStatus",
    "GeminiDiffStat",
    # Token types
    "GeminiTokensSummary",
    # Thought types
    "GeminiThoughtSummary",
    "GeminiTimestampedThought",
    # Tool args
    "GeminiToolCallArgs",
    "GeminiWriteFileArgs",
    "GeminiEditArgs",
    "GeminiShellArgs",
    # Transform
    "transform_gemini_v1",
]
