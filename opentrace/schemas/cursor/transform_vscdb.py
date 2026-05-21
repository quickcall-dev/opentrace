# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Transform Cursor state.vscdb (cursorDiskKV) sessions to unified format."""


import json
from datetime import datetime, timezone
from typing import Any, Literal

from opentrace.schemas.unified import (
    NormalizedMessage,
    TokenUsage,
    ToolCall,
    ToolResult,
)
from opentrace.utils.vscdb import (
    VscdbSession,
    _decompress,
    _extract_hashes,
)


def transform_cursor_vscdb(session: VscdbSession) -> list[NormalizedMessage]:
    """Transform a VscdbSession into normalized messages.

    Dispatches to mode-specific transform based on composerData structure.
    """
    mode = _detect_mode(session.composer_data)
    if mode == "inline":
        return _transform_inline(session)
    elif mode == "hashchain":
        messages = _transform_hashchain(session)
        if not messages:
            # Fallback: blobs may be missing/deleted, try headers_only if available
            headers = session.composer_data.get("fullConversationHeadersOnly")
            if headers and isinstance(headers, list) and len(headers) > 0:
                return _transform_headers_only(session)
        return messages
    else:
        return _transform_headers_only(session)


def _detect_mode(cd: dict) -> Literal["inline", "hashchain", "headers_only"]:
    """Detect which storage mode the composerData uses.

    - inline: has conversation[] with text content in bubbles
    - hashchain: has conversationState (base64-encoded protobuf with hashes pointing to agentKv blobs)
    - headers_only: has fullConversationHeadersOnly[] (bubble IDs only, no inline content)
    """
    if cd.get("conversation") and isinstance(cd["conversation"], list) and len(cd["conversation"]) > 0:
        # Check if bubbles actually have text content (not just headers)
        for bubble in cd["conversation"]:
            if isinstance(bubble, dict) and bubble.get("text"):
                return "inline"

    if cd.get("conversationState") and isinstance(cd["conversationState"], str):
        return "hashchain"

    if cd.get("fullConversationHeadersOnly") and isinstance(cd["fullConversationHeadersOnly"], list):
        return "headers_only"

    # Fallback: if conversation exists but no text, treat as headers_only
    if cd.get("conversation"):
        return "headers_only"

    return "headers_only"


def _transform_inline(session: VscdbSession) -> list[NormalizedMessage]:
    """Transform inline mode: conversation[] has full text content.

    Timestamps: timingInfo.clientStartTime for assistant bubbles,
    composerData.createdAt for user bubbles and fallback.
    Tool calls identified by isCapabilityIteration=True.
    Tokens from bubbleId lookup.
    """
    messages: list[NormalizedMessage] = []
    cd = session.composer_data
    conversation = cd.get("conversation", [])
    fallback_ts = _ms_to_iso(cd.get("createdAt", 0))
    model = _extract_model(cd)

    for i, bubble in enumerate(conversation):
        if not isinstance(bubble, dict):
            continue

        bubble_type = bubble.get("type", 0)
        bubble_id = bubble.get("bubbleId", "")
        text = bubble.get("text", "")
        timing = bubble.get("timingInfo") or {}
        is_capability = bubble.get("isCapabilityIteration", False) or bubble.get("capabilityType") is not None
        capability_type = bubble.get("capabilityType", "")

        # Determine timestamp
        client_start = timing.get("clientStartTime")
        ts = _ms_to_iso(client_start) if client_start else fallback_ts

        # Get token usage from bubble entry
        tokens = _bubble_tokens(session, session.composer_id, bubble_id)

        # Extract thinking
        thinking = None
        thinking_blocks = bubble.get("allThinkingBlocks", [])
        if thinking_blocks:
            parts = []
            for tb in thinking_blocks:
                if isinstance(tb, dict) and tb.get("thinking"):
                    parts.append(tb["thinking"])
            if parts:
                thinking = "\n\n".join(parts)

        if is_capability:
            # Tool call bubble
            msg_id = f"{session.composer_id}-{i}"
            tool_name = str(capability_type) if capability_type else "unknown"
            messages.append(NormalizedMessage(
                id=msg_id,
                session_id=session.composer_id,
                source="cursor_vscdb",
                source_schema_version=2,
                msg_type="tool_call",
                timestamp=ts,
                content=text if text else None,
                tokens=tokens,
                tool_call=ToolCall(
                    id=msg_id,
                    name=tool_name,
                    input={},
                ),
                model=model,
                raw_file_path=session.db_path,
            ))
        elif bubble_type == 1:
            # User message
            messages.append(NormalizedMessage(
                id=f"{session.composer_id}-{i}",
                session_id=session.composer_id,
                source="cursor_vscdb",
                source_schema_version=2,
                msg_type="user",
                timestamp=ts if not client_start else fallback_ts,
                content=text if text else None,
                tokens=tokens,
                model=model,
                raw_file_path=session.db_path,
            ))
        elif bubble_type == 2:
            # Assistant message
            messages.append(NormalizedMessage(
                id=f"{session.composer_id}-{i}",
                session_id=session.composer_id,
                source="cursor_vscdb",
                source_schema_version=2,
                msg_type="assistant",
                timestamp=ts,
                content=text if text else None,
                tokens=tokens,
                thinking=thinking,
                model=model,
                raw_file_path=session.db_path,
            ))
        else:
            # Unknown type, emit as assistant
            if text:
                messages.append(NormalizedMessage(
                    id=f"{session.composer_id}-{i}",
                    session_id=session.composer_id,
                    source="cursor_vscdb",
                    source_schema_version=2,
                    msg_type="assistant",
                    timestamp=ts,
                    content=text,
                    tokens=tokens,
                    model=model,
                    raw_file_path=session.db_path,
                ))

    return messages


def _transform_hashchain(session: VscdbSession) -> list[NormalizedMessage]:
    """Transform hashchain mode: conversationState → base64 → protobuf → SHA-256 → agentKv blobs.

    Timestamps: composerData.createdAt (session-level only).
    Tool results from agentKv role:tool entries with real status.
    """
    messages: list[NormalizedMessage] = []
    cd = session.composer_data
    fallback_ts = _ms_to_iso(cd.get("createdAt", 0))
    model = _extract_model(cd)

    conversation_state = cd.get("conversationState", "")
    hashes = _extract_hashes(conversation_state)

    for i, h in enumerate(hashes):
        kv_key = f"agentKv:blob:{h}"
        raw = session.agent_kv_entries.get(kv_key)
        if raw is None:
            continue

        parsed = _parse_agent_kv_json(raw)
        if parsed is None:
            continue

        role = parsed.get("role", "")
        msg_id = f"{session.composer_id}-hc-{i}"

        if role == "user":
            content_parts = parsed.get("content", [])
            text = _extract_text_from_content(content_parts)
            messages.append(NormalizedMessage(
                id=msg_id,
                session_id=session.composer_id,
                source="cursor_vscdb",
                source_schema_version=2,
                msg_type="user",
                timestamp=fallback_ts,
                content=text,
                model=model,
                raw_file_path=session.db_path,
            ))
        elif role == "assistant":
            content_parts = parsed.get("content", [])
            text = _extract_text_from_content(content_parts)
            tool_calls = _extract_tool_calls_from_content(content_parts, msg_id)

            if text:
                messages.append(NormalizedMessage(
                    id=msg_id,
                    session_id=session.composer_id,
                    source="cursor_vscdb",
                    source_schema_version=2,
                    msg_type="assistant",
                    timestamp=fallback_ts,
                    content=text,
                    model=model,
                    raw_file_path=session.db_path,
                ))

            for j, tc in enumerate(tool_calls):
                tc_id = f"{msg_id}-tc-{j}"
                messages.append(NormalizedMessage(
                    id=tc_id,
                    session_id=session.composer_id,
                    source="cursor_vscdb",
                    source_schema_version=2,
                    msg_type="tool_call",
                    timestamp=fallback_ts,
                    tool_call=tc,
                    model=model,
                    raw_file_path=session.db_path,
                ))
        elif role == "tool":
            tool_call_id = parsed.get("id") or parsed.get("tool_call_id") or msg_id
            content_parts = parsed.get("content", [])
            output = _extract_text_from_content(content_parts)
            # Determine status from content blocks or providerOptions
            status: Literal["success", "failure"] = "success"
            provider = parsed.get("providerOptions", {})
            cursor_opts = provider.get("cursor", {}) if isinstance(provider, dict) else {}
            high_level = cursor_opts.get("highLevelToolCallResult", {}) if isinstance(cursor_opts, dict) else {}
            if isinstance(high_level, dict) and high_level.get("isError"):
                status = "failure"
            elif isinstance(content_parts, list):
                for part in content_parts:
                    if isinstance(part, dict) and (part.get("is_error") or part.get("isError")):
                        status = "failure"
                        break
            messages.append(NormalizedMessage(
                id=msg_id,
                session_id=session.composer_id,
                source="cursor_vscdb",
                source_schema_version=2,
                msg_type="tool_result",
                timestamp=fallback_ts,
                tool_result=ToolResult(
                    call_id=tool_call_id,
                    output=output or "",
                    status=status,
                ),
                model=model,
                raw_file_path=session.db_path,
            ))

    return messages


def _transform_headers_only(session: VscdbSession) -> list[NormalizedMessage]:
    """Transform headers-only mode: fullConversationHeadersOnly with bubble ID lookups.

    Tokens from bubbleId entries. Minimal content (none from headers).
    Timestamps from bubbleId.createdAt (v3) or composerData.createdAt.
    """
    messages: list[NormalizedMessage] = []
    cd = session.composer_data
    fallback_ts = _ms_to_iso(cd.get("createdAt", 0))
    model = _extract_model(cd)

    headers = cd.get("fullConversationHeadersOnly") or cd.get("conversation") or []

    for i, bubble in enumerate(headers):
        if not isinstance(bubble, dict):
            continue

        bubble_type = bubble.get("type", 0)
        bubble_id = bubble.get("bubbleId", "")
        is_capability = bubble.get("isCapabilityIteration", False) or bubble.get("capabilityType") is not None

        # Look up bubble entry for tokens and timestamp
        tokens = _bubble_tokens(session, session.composer_id, bubble_id)
        bubble_entry = session.bubble_entries.get(
            f"bubbleId:{session.composer_id}:{bubble_id}"
        )

        ts = fallback_ts
        if bubble_entry and bubble_entry.get("createdAt"):
            ts = _ms_to_iso(bubble_entry["createdAt"])

        content = bubble_entry.get("text") or None if bubble_entry else None

        # Extract thinking blocks for assistant bubbles
        thinking = None
        if bubble_entry and bubble_type == 2:
            blocks = bubble_entry.get("allThinkingBlocks") or []
            if blocks:
                thinking = "\n".join(b.get("thinking", "") for b in blocks if b.get("thinking"))
            thinking = thinking or None

        msg_id = f"{session.composer_id}-ho-{i}"

        if is_capability:
            capability_type = bubble.get("capabilityType", "unknown")
            messages.append(NormalizedMessage(
                id=msg_id,
                session_id=session.composer_id,
                source="cursor_vscdb",
                source_schema_version=2,
                msg_type="tool_call",
                timestamp=ts,
                tokens=tokens,
                content=content,
                tool_call=ToolCall(id=msg_id, name=str(capability_type) if capability_type else "unknown", input={}),
                model=model,
                raw_file_path=session.db_path,
            ))
        elif bubble_type == 1:
            messages.append(NormalizedMessage(
                id=msg_id,
                session_id=session.composer_id,
                source="cursor_vscdb",
                source_schema_version=2,
                msg_type="user",
                timestamp=ts,
                tokens=tokens,
                content=content,
                model=model,
                raw_file_path=session.db_path,
            ))
        elif bubble_type == 2:
            messages.append(NormalizedMessage(
                id=msg_id,
                session_id=session.composer_id,
                source="cursor_vscdb",
                source_schema_version=2,
                msg_type="assistant",
                timestamp=ts,
                tokens=tokens,
                content=content,
                thinking=thinking,
                model=model,
                raw_file_path=session.db_path,
            ))

    return messages


# --- Helpers ---


def _extract_model(cd: dict) -> str | None:
    """Extract model name from composerData.modelConfig."""
    mc = cd.get("modelConfig")
    if isinstance(mc, dict):
        return mc.get("modelName")
    return None


def _ms_to_iso(ms: int | str) -> str:
    """Convert millisecond epoch to ISO 8601 string. Returns empty string for 0/None."""
    if not ms:
        return ""
    try:
        ms = int(ms)
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        return dt.isoformat()
    except (OSError, ValueError, OverflowError):
        return ""


def _bubble_tokens(session: VscdbSession, composer_id: str, bubble_id: str) -> TokenUsage:
    """Look up token counts from the bubbleId entry."""
    if not bubble_id:
        return TokenUsage()
    key = f"bubbleId:{composer_id}:{bubble_id}"
    entry = session.bubble_entries.get(key)
    if not entry:
        return TokenUsage()
    tc = entry.get("tokenCount")
    if not isinstance(tc, dict):
        return TokenUsage()
    return TokenUsage(
        input=tc.get("inputTokens", 0),
        output=tc.get("outputTokens", 0),
    )


def _parse_agent_kv_json(raw: bytes) -> dict | None:
    """Decompress (if needed) and parse agent KV blob as JSON dict."""
    try:
        decompressed = _decompress(raw)
        text = decompressed.decode("utf-8", errors="replace")
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        pass
    return None


def _extract_text_from_content(content: Any) -> str | None:
    """Extract text from a content array (list of content blocks) or string.

    Supports standard text blocks (type='text') and Cursor's tool-result
    blocks (type='tool-result' with 'result' field).
    """
    if isinstance(content, str):
        return content if content else None
    if not isinstance(content, list):
        return None
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            if block.get("type") == "text" and block.get("text"):
                parts.append(block["text"])
            elif block.get("type") == "tool-result" and block.get("result"):
                parts.append(block["result"])
    return "\n".join(parts) if parts else None


def _extract_tool_calls_from_content(content: Any, parent_id: str) -> list[ToolCall]:
    """Extract tool_use / tool-call blocks from a content array.

    Supports both Anthropic format (type='tool_use') and Cursor's agentKv
    format (type='tool-call' with toolName/toolCallId/args).
    """
    if not isinstance(content, list):
        return []
    calls = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "tool_use":
            calls.append(ToolCall(
                id=block.get("id", parent_id),
                name=block.get("name", "unknown"),
                input=block.get("input", {}),
            ))
        elif block_type == "tool-call":
            calls.append(ToolCall(
                id=block.get("toolCallId", parent_id),
                name=block.get("toolName", "unknown"),
                input=block.get("args", {}),
            ))
    return calls
