# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for opentrace.schemas.cursor.transform_vscdb."""

import base64
import json

from opentrace.daemon.collector import _extract_workspace_path
from opentrace.schemas.unified import NormalizedMessage
from opentrace.schemas.cursor.transform_vscdb import (
    _detect_mode,
    _ms_to_iso,
    _extract_model,
    _bubble_tokens,
    transform_cursor_vscdb,
)
from opentrace.utils.vscdb import (
    _decode_varint,
    _extract_hashes,
)
from opentrace.utils.vscdb import VscdbSession


def _make_session(
    composer_id: str = "test-id",
    composer_data: dict | None = None,
    bubble_entries: dict | None = None,
    agent_kv_entries: dict | None = None,
    db_path: str = "/test/state.vscdb",
) -> VscdbSession:
    return VscdbSession(
        composer_id=composer_id,
        composer_data=composer_data or {},
        bubble_entries=bubble_entries or {},
        agent_kv_entries=agent_kv_entries or {},
        db_path=db_path,
    )


class TestDetectMode:
    def test_inline_with_text(self):
        cd = {"conversation": [{"type": 1, "text": "hello", "bubbleId": "b1"}]}
        assert _detect_mode(cd) == "inline"

    def test_hashchain_with_state(self):
        cd = {"conversationState": "some_base64_data"}
        assert _detect_mode(cd) == "hashchain"

    def test_headers_only(self):
        cd = {"fullConversationHeadersOnly": [{"type": 1, "bubbleId": "b1"}]}
        assert _detect_mode(cd) == "headers_only"

    def test_empty_conversation_is_headers_only(self):
        cd = {"conversation": []}
        assert _detect_mode(cd) == "headers_only"

    def test_conversation_without_text_is_headers_only(self):
        cd = {"conversation": [{"type": 1, "bubbleId": "b1"}]}
        assert _detect_mode(cd) == "headers_only"

    def test_empty_dict(self):
        assert _detect_mode({}) == "headers_only"


class TestMsToIso:
    def test_converts_ms(self):
        result = _ms_to_iso(1708000000000)
        assert "2024-02-15" in result
        assert result.endswith("+00:00")

    def test_zero_returns_empty(self):
        assert _ms_to_iso(0) == ""

    def test_none_returns_empty(self):
        assert _ms_to_iso(None) == ""


class TestExtractModel:
    def test_extracts_model(self):
        cd = {"modelConfig": {"modelName": "claude-3.5-sonnet"}}
        assert _extract_model(cd) == "claude-3.5-sonnet"

    def test_no_model_config(self):
        assert _extract_model({}) is None

    def test_no_model_name(self):
        cd = {"modelConfig": {}}
        assert _extract_model(cd) is None


class TestBubbleTokens:
    def test_finds_tokens(self):
        session = _make_session(
            composer_id="cid",
            bubble_entries={
                "bubbleId:cid:b1": {
                    "tokenCount": {"inputTokens": 50, "outputTokens": 100}
                }
            },
        )
        tokens = _bubble_tokens(session, "cid", "b1")
        assert tokens.input == 50
        assert tokens.output == 100

    def test_missing_bubble(self):
        session = _make_session()
        tokens = _bubble_tokens(session, "cid", "missing")
        assert tokens.input == 0
        assert tokens.output == 0

    def test_empty_bubble_id(self):
        session = _make_session()
        tokens = _bubble_tokens(session, "cid", "")
        assert tokens.input == 0


class TestDecodeVarint:
    def test_single_byte(self):
        val, pos = _decode_varint(b"\x05", 0)
        assert val == 5
        assert pos == 1

    def test_multi_byte(self):
        val, pos = _decode_varint(b"\xac\x02", 0)
        assert val == 300
        assert pos == 2

    def test_with_offset(self):
        val, pos = _decode_varint(b"\x00\x05", 1)
        assert val == 5
        assert pos == 2


class TestExtractHashes:
    def test_empty_string(self):
        assert _extract_hashes("") == []

    def test_invalid_base64(self):
        assert _extract_hashes("!!!invalid!!!") == []

    def test_extracts_hashes_from_protobuf(self):
        # Build a minimal protobuf with a 32-byte length-delimited field
        # Field 1, wire type 2 (length-delimited): tag = (1 << 3) | 2 = 0x0a
        hash_bytes = bytes(range(32))  # 32-byte "hash"
        proto = bytes([0x0a, 0x20]) + hash_bytes  # tag + length(32) + data
        encoded = base64.b64encode(proto).decode()

        result = _extract_hashes(encoded)
        assert len(result) == 1
        assert result[0] == hash_bytes.hex()

    def test_strips_tilde_prefix(self):
        hash_bytes = bytes(range(32))
        proto = bytes([0x0a, 0x20]) + hash_bytes
        encoded = "~" + base64.b64encode(proto).decode()

        result = _extract_hashes(encoded)
        assert len(result) == 1


class TestTransformInline:
    def test_user_and_assistant(self):
        session = _make_session(
            composer_id="s1",
            composer_data={
                "createdAt": 1708000000000,
                "conversation": [
                    {"type": 1, "bubbleId": "b1", "text": "Hello"},
                    {"type": 2, "bubbleId": "b2", "text": "Hi!", "timingInfo": {"clientStartTime": 1708000001000}},
                ],
                "modelConfig": {"modelName": "gpt-4o"},
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert len(msgs) == 2
        assert msgs[0].msg_type == "user"
        assert msgs[0].content == "Hello"
        assert msgs[0].source == "cursor_vscdb"
        assert msgs[0].source_schema_version == 2
        assert msgs[1].msg_type == "assistant"
        assert msgs[1].content == "Hi!"
        assert msgs[1].model == "gpt-4o"
        assert "2024-02-15" in msgs[1].timestamp

    def test_tool_call_bubble(self):
        session = _make_session(
            composer_data={
                "createdAt": 1708000000000,
                "conversation": [
                    {"type": 2, "bubbleId": "b1", "text": "", "isCapabilityIteration": True, "capabilityType": "code_edit"},
                ],
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert len(msgs) == 1
        assert msgs[0].msg_type == "tool_call"
        assert msgs[0].tool_call.name == "code_edit"

    def test_thinking_blocks(self):
        session = _make_session(
            composer_data={
                "createdAt": 1708000000000,
                "conversation": [
                    {
                        "type": 2, "bubbleId": "b1", "text": "Answer",
                        "allThinkingBlocks": [{"thinking": "Let me think..."}],
                    },
                ],
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert msgs[0].thinking == "Let me think..."

    def test_tokens_from_bubble_entry(self):
        session = _make_session(
            composer_id="s1",
            composer_data={
                "createdAt": 1708000000000,
                "conversation": [
                    {"type": 2, "bubbleId": "b1", "text": "Response"},
                ],
            },
            bubble_entries={
                "bubbleId:s1:b1": {"tokenCount": {"inputTokens": 200, "outputTokens": 300}},
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert msgs[0].tokens.input == 200
        assert msgs[0].tokens.output == 300


class TestTransformHashchain:
    def test_basic_hashchain(self):

        # Build protobuf with one hash
        hash_bytes = b"\x01" * 32
        proto = bytes([0x0a, 0x20]) + hash_bytes
        conv_state = base64.b64encode(proto).decode()

        # Build agent KV entry
        agent_kv_data = json.dumps({"role": "user", "content": [{"type": "text", "text": "Hello from hashchain"}]}).encode()

        session = _make_session(
            composer_data={
                "createdAt": 1708000000000,
                "conversationState": conv_state,
                "modelConfig": {"modelName": "claude-3.5-sonnet"},
            },
            agent_kv_entries={
                f"agentKv:blob:{hash_bytes.hex()}": agent_kv_data,
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert len(msgs) == 1
        assert msgs[0].msg_type == "user"
        assert msgs[0].content == "Hello from hashchain"

    def test_tool_result_with_error(self):

        hash_bytes = b"\x02" * 32
        proto = bytes([0x0a, 0x20]) + hash_bytes
        conv_state = base64.b64encode(proto).decode()

        agent_kv_data = json.dumps({
            "role": "tool",
            "id": "call-123",
            "content": [{"type": "text", "text": "Error occurred", "is_error": True}],
        }).encode()

        session = _make_session(
            composer_data={
                "createdAt": 1708000000000,
                "conversationState": conv_state,
            },
            agent_kv_entries={
                f"agentKv:blob:{hash_bytes.hex()}": agent_kv_data,
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert len(msgs) == 1
        assert msgs[0].msg_type == "tool_result"
        assert msgs[0].tool_result.status == "failure"
        assert msgs[0].tool_result.call_id == "call-123"


class TestTransformHeadersOnly:
    def test_basic_headers(self):
        session = _make_session(
            composer_id="ho-1",
            composer_data={
                "createdAt": 1708000000000,
                "fullConversationHeadersOnly": [
                    {"type": 1, "bubbleId": "b1"},
                    {"type": 2, "bubbleId": "b2"},
                ],
                "modelConfig": {"modelName": "gpt-4o"},
            },
            bubble_entries={
                "bubbleId:ho-1:b1": {"_v": 3, "text": "Hello, help me refactor this code", "tokenCount": {"inputTokens": 50, "outputTokens": 0}, "createdAt": 1708000001000},
                "bubbleId:ho-1:b2": {"_v": 3, "text": "Sure, I can help with that.", "tokenCount": {"inputTokens": 50, "outputTokens": 150}, "createdAt": 1708000002000, "allThinkingBlocks": [{"thinking": "Let me analyze the code"}]},
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert len(msgs) == 2
        assert msgs[0].msg_type == "user"
        assert msgs[0].tokens.input == 50
        assert msgs[0].content == "Hello, help me refactor this code"
        assert msgs[1].msg_type == "assistant"
        assert msgs[1].tokens.output == 150
        assert msgs[1].content == "Sure, I can help with that."
        assert msgs[1].thinking == "Let me analyze the code"
        assert msgs[1].model == "gpt-4o"
        # Should use bubbleId.createdAt for timestamp
        assert "2024-02-15" in msgs[1].timestamp

    def test_tool_call_header(self):
        session = _make_session(
            composer_data={
                "createdAt": 1708000000000,
                "fullConversationHeadersOnly": [
                    {"type": 2, "bubbleId": "b1", "isCapabilityIteration": True, "capabilityType": "terminal"},
                ],
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert len(msgs) == 1
        assert msgs[0].msg_type == "tool_call"
        assert msgs[0].tool_call.name == "terminal"


class TestHashchainFallback:
    def test_falls_back_to_headers_only_when_blobs_missing(self):
        """When hashchain mode produces 0 messages (no blobs), fall back to headers_only."""

        # Build a valid conversationState with a hash, but don't provide the blob
        hash_bytes = b"\xaa" * 32
        proto = bytes([0x0a, 0x20]) + hash_bytes
        conv_state = base64.b64encode(proto).decode()

        session = _make_session(
            composer_id="fb-1",
            composer_data={
                "createdAt": 1708000000000,
                "conversationState": conv_state,
                "fullConversationHeadersOnly": [
                    {"type": 1, "bubbleId": "b1"},
                    {"type": 2, "bubbleId": "b2"},
                ],
                "modelConfig": {"modelName": "gpt-4o"},
            },
            bubble_entries={
                "bubbleId:fb-1:b1": {"_v": 3, "text": "User question", "tokenCount": {"inputTokens": 10, "outputTokens": 0}, "createdAt": 1708000001000},
                "bubbleId:fb-1:b2": {"_v": 3, "text": "Assistant answer", "tokenCount": {"inputTokens": 10, "outputTokens": 50}, "createdAt": 1708000002000},
            },
            agent_kv_entries={},  # No blobs!
        )
        msgs = transform_cursor_vscdb(session)
        assert len(msgs) == 2
        assert msgs[0].msg_type == "user"
        assert msgs[0].content == "User question"
        assert msgs[1].msg_type == "assistant"
        assert msgs[1].content == "Assistant answer"

    def test_no_fallback_when_hashchain_has_messages(self):
        """When hashchain produces messages, don't fall back."""

        hash_bytes = b"\xbb" * 32
        proto = bytes([0x0a, 0x20]) + hash_bytes
        conv_state = base64.b64encode(proto).decode()

        session = _make_session(
            composer_data={
                "createdAt": 1708000000000,
                "conversationState": conv_state,
                "fullConversationHeadersOnly": [
                    {"type": 1, "bubbleId": "b1"},
                ],
            },
            agent_kv_entries={
                f"agentKv:blob:{hash_bytes.hex()}": json.dumps({"role": "user", "content": "Hello"}).encode(),
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert len(msgs) == 1
        assert msgs[0].msg_type == "user"
        assert msgs[0].content == "Hello"


class TestExtractWorkspacePath:
    def test_extracts_from_user_info_block(self):

        msgs = [
            NormalizedMessage(
                id="1", session_id="s1", source="cursor_vscdb",
                source_schema_version=2, msg_type="user", timestamp="",
                content="<user_info>\nOS Version: darwin 25.2.0\nShell: zsh\nWorkspace Path: /Users/test/work/project\n</user_info>\nhey there",
            ),
            NormalizedMessage(
                id="2", session_id="s1", source="cursor_vscdb",
                source_schema_version=2, msg_type="assistant", timestamp="",
                content="Hello!",
            ),
        ]
        assert _extract_workspace_path(msgs) == "/Users/test/work/project"

    def test_returns_none_when_no_workspace_path(self):

        msgs = [
            NormalizedMessage(
                id="1", session_id="s1", source="cursor_vscdb",
                source_schema_version=2, msg_type="user", timestamp="",
                content="just a regular message",
            ),
        ]
        assert _extract_workspace_path(msgs) is None

    def test_returns_none_for_empty_messages(self):
        assert _extract_workspace_path([]) is None


class TestInlineCapabilityType:
    """Bug: inline mode checks isCapabilityIteration (always False in real data).
    Should also check capabilityType is not None. Real Cursor data has
    capabilityType=15 with isCapabilityIteration=False on 1,367 bubbles."""

    def test_capability_type_without_iteration_flag(self):
        """capabilityType=15, isCapabilityIteration=False should be a tool_call."""
        session = _make_session(
            composer_data={
                "createdAt": 1708000000000,
                "conversation": [
                    {"type": 1, "bubbleId": "b1", "text": "Create a file"},
                    {
                        "type": 2, "bubbleId": "b2", "text": "",
                        "isCapabilityIteration": False,
                        "capabilityType": 15,
                    },
                    {"type": 2, "bubbleId": "b3", "text": "I created the file."},
                ],
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert len(msgs) == 3
        assert msgs[0].msg_type == "user"
        assert msgs[1].msg_type == "tool_call"
        assert msgs[1].tool_call.name == "15"
        assert msgs[2].msg_type == "assistant"

    def test_capability_type_none_is_not_tool_call(self):
        """capabilityType=None should remain a normal assistant message."""
        session = _make_session(
            composer_data={
                "createdAt": 1708000000000,
                "conversation": [
                    {"type": 2, "bubbleId": "b1", "text": "Hello",
                     "capabilityType": None, "isCapabilityIteration": False},
                ],
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert len(msgs) == 1
        assert msgs[0].msg_type == "assistant"

    def test_headers_only_capability_type_without_iteration_flag(self):
        """Same bug exists in headers_only mode."""
        session = _make_session(
            composer_data={
                "createdAt": 1708000000000,
                "fullConversationHeadersOnly": [
                    {
                        "type": 2, "bubbleId": "b1",
                        "isCapabilityIteration": False,
                        "capabilityType": 15,
                    },
                ],
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert len(msgs) == 1
        assert msgs[0].msg_type == "tool_call"
        assert msgs[0].tool_call.name == "15"


class TestHashchainToolCalls:
    """Bug: Cursor agentKv uses type='tool-call' (not 'tool_use') and
    type='tool-result' (not 'text') in content blocks. The transform
    misses both because _extract_tool_calls_from_content checks 'tool_use'
    and _extract_text_from_content only checks 'text'."""

    def test_tool_call_blocks_extracted(self):
        """Assistant with type='tool-call' content blocks should produce tool_call messages."""

        h1 = b"\x11" * 32
        h2 = b"\x12" * 32
        proto = bytes([0x0a, 0x20]) + h1 + bytes([0x0a, 0x20]) + h2

        assistant_entry = json.dumps({
            "id": "msg-1",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me read that file."},
                {
                    "type": "tool-call",
                    "toolName": "Read",
                    "toolCallId": "tool_abc123",
                    "args": {"filePath": "/src/main.py"},
                },
                {
                    "type": "tool-call",
                    "toolName": "Grep",
                    "toolCallId": "tool_def456",
                    "args": {"pattern": "def main"},
                },
            ],
        }).encode()

        user_entry = json.dumps({
            "role": "user",
            "content": [{"type": "text", "text": "Read main.py"}],
        }).encode()

        session = _make_session(
            composer_data={
                "createdAt": 1708000000000,
                "conversationState": base64.b64encode(proto).decode(),
            },
            agent_kv_entries={
                f"agentKv:blob:{h1.hex()}": user_entry,
                f"agentKv:blob:{h2.hex()}": assistant_entry,
            },
        )
        msgs = transform_cursor_vscdb(session)

        # Should have: user, assistant text, tool_call(Read), tool_call(Grep)
        assert len(msgs) == 4
        assert msgs[0].msg_type == "user"
        assert msgs[1].msg_type == "assistant"
        assert msgs[1].content == "Let me read that file."
        assert msgs[2].msg_type == "tool_call"
        assert msgs[2].tool_call.name == "Read"
        assert msgs[2].tool_call.id == "tool_abc123"
        assert msgs[2].tool_call.input == {"filePath": "/src/main.py"}
        assert msgs[3].msg_type == "tool_call"
        assert msgs[3].tool_call.name == "Grep"

    def test_tool_result_blocks_extracted(self):
        """Tool results with type='tool-result' should have output extracted."""

        h1 = b"\x21" * 32
        proto = bytes([0x0a, 0x20]) + h1

        tool_entry = json.dumps({
            "role": "tool",
            "id": "tool_abc123",
            "content": [
                {
                    "type": "tool-result",
                    "toolName": "Read",
                    "toolCallId": "tool_abc123",
                    "result": "def main():\n    print('hello')",
                },
            ],
        }).encode()

        session = _make_session(
            composer_data={
                "createdAt": 1708000000000,
                "conversationState": base64.b64encode(proto).decode(),
            },
            agent_kv_entries={
                f"agentKv:blob:{h1.hex()}": tool_entry,
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert len(msgs) == 1
        assert msgs[0].msg_type == "tool_result"
        assert msgs[0].tool_result.output == "def main():\n    print('hello')"
        assert msgs[0].tool_result.call_id == "tool_abc123"
        assert msgs[0].tool_result.status == "success"

    def test_tool_result_with_error(self):
        """Tool result with isError should have status=failure."""

        h1 = b"\x31" * 32
        proto = bytes([0x0a, 0x20]) + h1

        tool_entry = json.dumps({
            "role": "tool",
            "id": "tool_err",
            "content": [
                {
                    "type": "tool-result",
                    "toolName": "Bash",
                    "toolCallId": "tool_err",
                    "result": "command not found: foobar",
                    "isError": True,
                },
            ],
            "providerOptions": {"cursor": {"highLevelToolCallResult": {"isError": True}}},
        }).encode()

        session = _make_session(
            composer_data={
                "createdAt": 1708000000000,
                "conversationState": base64.b64encode(proto).decode(),
            },
            agent_kv_entries={
                f"agentKv:blob:{h1.hex()}": tool_entry,
            },
        )
        msgs = transform_cursor_vscdb(session)
        assert len(msgs) == 1
        assert msgs[0].tool_result.status == "failure"
        assert msgs[0].tool_result.output == "command not found: foobar"

    def test_mixed_conversation_with_tools(self):
        """Full conversation: user → assistant+tool_calls → tool_results → assistant."""

        hashes = [bytes([i]) * 32 for i in range(0x41, 0x46)]
        proto = b"".join(bytes([0x0a, 0x20]) + h for h in hashes)

        entries = {
            f"agentKv:blob:{hashes[0].hex()}": json.dumps({
                "role": "user", "content": "Search for main function"
            }).encode(),
            f"agentKv:blob:{hashes[1].hex()}": json.dumps({
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll search for that."},
                    {"type": "tool-call", "toolName": "Grep", "toolCallId": "tc1", "args": {"pattern": "def main"}},
                ],
            }).encode(),
            f"agentKv:blob:{hashes[2].hex()}": json.dumps({
                "role": "tool", "id": "tc1",
                "content": [{"type": "tool-result", "toolName": "Grep", "toolCallId": "tc1", "result": "src/app.py:10: def main():"}],
            }).encode(),
            f"agentKv:blob:{hashes[3].hex()}": json.dumps({
                "role": "assistant",
                "content": [{"type": "text", "text": "Found it in src/app.py line 10."}],
            }).encode(),
        }

        session = _make_session(
            composer_data={
                "createdAt": 1708000000000,
                "conversationState": base64.b64encode(proto).decode(),
            },
            agent_kv_entries=entries,
        )
        msgs = transform_cursor_vscdb(session)

        types = [m.msg_type for m in msgs]
        assert types == ["user", "assistant", "tool_call", "tool_result", "assistant"]
        assert msgs[2].tool_call.name == "Grep"
        assert msgs[3].tool_result.output == "src/app.py:10: def main():"
        assert msgs[4].content == "Found it in src/app.py line 10."


class TestTransformEmpty:
    def test_empty_session(self):
        session = _make_session(composer_data={})
        msgs = transform_cursor_vscdb(session)
        assert msgs == []
