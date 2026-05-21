# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Claude Code schema definitions and transformations."""

from opentrace.schemas.claude_code.v1 import (
    ClaudeAssistantMessage,
    ClaudeContentBlock,
    ClaudeMessage,
    ClaudeTextBlock,
    ClaudeThinkingBlock,
    ClaudeToolResultBlock,
    ClaudeToolUseBlock,
    ClaudeUsage,
    ClaudeUserMessage,
)
from opentrace.schemas.claude_code.transform import transform_claude_v1

__all__ = [
    "ClaudeMessage",
    "ClaudeUserMessage",
    "ClaudeAssistantMessage",
    "ClaudeContentBlock",
    "ClaudeTextBlock",
    "ClaudeThinkingBlock",
    "ClaudeToolUseBlock",
    "ClaudeToolResultBlock",
    "ClaudeUsage",
    "transform_claude_v1",
]
