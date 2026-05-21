# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for pi.dev schema transforms."""


from opentrace.schemas.pi.transform import transform_pi_v1


class TestTransformPiV1:
    def test_skips_session_event(self):
        event = {
            "type": "session",
            "version": 3,
            "id": "sess-1",
            "timestamp": "2026-05-20T15:25:16.862Z",
            "cwd": "/home/user/project",
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 1)
        assert result == []

    def test_skips_model_change(self):
        event = {
            "type": "model_change",
            "id": "m1",
            "parentId": None,
            "timestamp": "2026-05-20T15:25:18.220Z",
            "provider": "test-provider",
            "modelId": "test-model-v2",
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 2)
        assert result == []

    def test_skips_custom(self):
        event = {
            "type": "custom",
            "customType": "handoff:last-skill",
            "data": {"skillName": "doc"},
            "id": "c1",
            "parentId": "p1",
            "timestamp": "2026-05-20T15:25:20.000Z",
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 3)
        assert result == []

    def test_transforms_user_message(self):
        event = {
            "type": "message",
            "id": "msg-1",
            "parentId": "p1",
            "timestamp": "2026-05-20T15:28:55.917Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "start pi-port-skills"}],
                "timestamp": 1777232135014,
            },
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 4)
        assert len(result) == 1
        assert result[0].msg_type == "user"
        assert result[0].content == "start pi-port-skills"
        assert result[0].source == "pi"
        assert result[0].session_id == "sess-1"

    def test_transforms_assistant_message(self):
        event = {
            "type": "message",
            "id": "msg-2",
            "parentId": "msg-1",
            "timestamp": "2026-05-20T15:28:59.396Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll help you with that."},
                ],
                "api": "anthropic-messages",
                "provider": "test-provider",
                "model": "test-model-v2",
                "usage": {"input": 100, "output": 50, "cacheRead": 10, "cacheWrite": 0, "totalTokens": 160},
                "stopReason": "stop",
                "timestamp": 1777232135043,
            },
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 5)
        assert len(result) == 1
        msg = result[0]
        assert msg.msg_type == "assistant"
        assert msg.content == "I'll help you with that."
        assert msg.model == "test-model-v2"
        assert msg.tokens.input == 100
        assert msg.tokens.output == 50
        assert msg.tokens.cached == 10
        assert msg.tokens.thinking == 0

    def test_transforms_assistant_with_thinking(self):
        event = {
            "type": "message",
            "id": "msg-3",
            "parentId": "msg-2",
            "timestamp": "2026-05-20T15:29:00.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Let me analyze this.", "thinkingSignature": "abc"},
                    {"type": "text", "text": "Done."},
                ],
                "model": "test-model-v2",
                "timestamp": 1777232135044,
            },
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 6)
        assert len(result) == 1
        assert result[0].thinking == "Let me analyze this."
        assert result[0].content == "Done."

    def test_transforms_assistant_with_tool_calls(self):
        event = {
            "type": "message",
            "id": "msg-4",
            "parentId": "msg-3",
            "timestamp": "2026-05-20T15:29:01.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Running command..."},
                    {"type": "toolCall", "id": "tool_1", "name": "bash", "arguments": {"command": "ls"}},
                ],
                "model": "test-model-v2",
                "timestamp": 1777232135045,
            },
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 7)
        assert len(result) == 2
        assert result[0].msg_type == "assistant"
        assert result[0].content == "Running command..."
        assert result[1].msg_type == "tool_call"
        assert result[1].tool_call.name == "bash"
        assert result[1].tool_call.input == {"command": "ls"}

    def test_transforms_tool_result(self):
        event = {
            "type": "message",
            "id": "msg-5",
            "parentId": "msg-4",
            "timestamp": "2026-05-20T15:29:02.000Z",
            "message": {
                "role": "toolResult",
                "toolCallId": "tool_1",
                "toolName": "bash",
                "content": [{"type": "text", "text": "README.md\nLICENSE"}],
                "isError": False,
                "timestamp": 1777232139619,
            },
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 8)
        assert len(result) == 1
        assert result[0].msg_type == "tool_result"
        assert result[0].tool_result.call_id == "tool_1"
        assert result[0].tool_result.output == "README.md\nLICENSE"
        assert result[0].tool_result.status == "success"

    def test_transforms_tool_result_error(self):
        event = {
            "type": "message",
            "id": "msg-6",
            "parentId": "msg-5",
            "timestamp": "2026-05-20T15:29:03.000Z",
            "message": {
                "role": "toolResult",
                "toolCallId": "tool_2",
                "toolName": "bash",
                "content": [{"type": "text", "text": "No such file"}],
                "isError": True,
                "timestamp": 1777232139620,
            },
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 9)
        assert result[0].tool_result.status == "failure"

    def test_skips_bash_execution(self):
        event = {
            "type": "message",
            "id": "msg-7",
            "parentId": "msg-6",
            "timestamp": "2026-05-20T15:29:04.000Z",
            "message": {
                "role": "bashExecution",
                "command": "ls",
                "output": "README.md",
                "exitCode": 0,
                "timestamp": 1777658785446,
            },
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 10)
        assert result == []

    def test_transforms_compaction(self):
        event = {
            "type": "compaction",
            "id": "comp-1",
            "parentId": "msg-8",
            "timestamp": "2026-05-20T15:50:45.668Z",
            "summary": "## Goal\nAdd pi harness...",
            "firstKeptEntryId": "msg-9",
            "tokensBefore": 262508,
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 11)
        assert len(result) == 1
        assert result[0].msg_type == "compaction"
        assert result[0].content == "## Goal\nAdd pi harness..."

    def test_uses_current_model_when_assistant_has_none(self):
        event = {
            "type": "message",
            "id": "msg-8",
            "parentId": "msg-7",
            "timestamp": "2026-05-20T15:29:05.000Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello"}],
                "timestamp": 1777232135046,
            },
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 12, current_model="test-model")
        assert result[0].model == "test-model"

    def test_source_is_pi(self):
        event = {
            "type": "message",
            "id": "msg-1",
            "parentId": None,
            "timestamp": "2026-05-20T15:28:55.917Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "hi"}],
                "timestamp": 1777232135014,
            },
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 1)
        assert result[0].source == "pi"

    def test_raw_file_path_and_line_number(self):
        event = {
            "type": "message",
            "id": "msg-1",
            "parentId": None,
            "timestamp": "2026-05-20T15:28:55.917Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "hi"}],
                "timestamp": 1777232135014,
            },
        }
        result = transform_pi_v1(event, "sess-1", "/tmp/pi.jsonl", 42)
        assert result[0].raw_file_path == "/tmp/pi.jsonl"
        assert result[0].raw_line_number == 42
