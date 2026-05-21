# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Cursor IDE Schema v2 — cursorDiskKV (state.vscdb) data shapes.

These TypedDicts describe the JSON structures stored in the
globalStorage/state.vscdb ItemTable under composerData:*, bubbleId:*,
and agentKv:blob:* keys.

Frozen 2026-02-20. Do NOT modify; create v3.py for format changes.
"""

from typing import TypedDict


class CursorTimingInfo(TypedDict, total=False):
    """Timing information for a bubble (message turn)."""

    clientStartTime: int  # ms epoch — when the client started the request
    clientRpcSendTime: int  # ms epoch — when the RPC was sent
    clientSettleTime: int  # ms epoch — when streaming settled
    clientEndTime: int  # ms epoch — when the turn fully completed


class CursorModelConfig(TypedDict, total=False):
    """Model configuration from composerData."""

    modelName: str  # e.g. "claude-3.5-sonnet", "gpt-4o"
    maxMode: bool  # whether "max mode" was enabled


class CursorBubbleTokenCount(TypedDict, total=False):
    """Token counts stored in a bubbleId entry."""

    inputTokens: int
    outputTokens: int


class CursorVscdbBubble(TypedDict, total=False):
    """A bubble (message) in the composerData conversation array.

    Used in inline mode where conversation[] is populated.
    """

    type: int  # 1=user, 2=assistant
    bubbleId: str
    text: str
    timingInfo: CursorTimingInfo
    tokenCountUpUntilHere: int  # cumulative token count
    isCapabilityIteration: bool  # True for tool call bubbles
    capabilityType: str  # e.g. "tool_call", "code_edit"
    allThinkingBlocks: list[dict]  # thinking block dicts


class CursorBubbleIdEntry(TypedDict, total=False):
    """A bubbleId:<cid>:<bid> entry from the ItemTable.

    Stores per-bubble metadata including token counts and creation time.
    """

    _v: int  # schema version (2 or 3)
    type: int  # bubble type
    tokenCount: CursorBubbleTokenCount
    createdAt: int  # ms epoch (present in v3 entries)


class CursorAgentKvToolResult(TypedDict, total=False):
    """A tool result entry from agentKv:blob:<hash>.

    role=tool entries in the hashchain conversation state.
    """

    role: str  # "tool", "assistant", "user"
    id: str  # tool call ID
    content: list[dict]  # content blocks
