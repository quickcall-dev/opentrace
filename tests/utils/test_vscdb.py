# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for opentrace.utils.vscdb — SQLite reader for state.vscdb."""

import base64
import json
import sqlite3
import zlib
from pathlib import Path

import pytest

from opentrace.utils.vscdb import (
    _decompress,
    _parse_json,
    iter_sessions,
    load_session,
    read_item_table,
    scan_session_timestamps,
)


@pytest.fixture
def vscdb_path(tmp_path: Path) -> str:
    """Create a temporary state.vscdb with test data."""
    db_path = str(tmp_path / "state.vscdb")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")

    # Insert a composerData entry
    composer_data = {
        "createdAt": 1708000000000,
        "conversation": [
            {"type": 1, "bubbleId": "b1", "text": "Hello"},
            {"type": 2, "bubbleId": "b2", "text": "Hi there"},
        ],
        "modelConfig": {"modelName": "claude-3.5-sonnet"},
        "createdOnBranch": "main",
    }
    conn.execute(
        "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
        ("composerData:abc-123", json.dumps(composer_data).encode()),
    )

    # Insert bubble entries
    bubble1 = {"_v": 3, "type": 1, "tokenCount": {"inputTokens": 100, "outputTokens": 0}, "createdAt": 1708000001000}
    bubble2 = {"_v": 3, "type": 2, "tokenCount": {"inputTokens": 100, "outputTokens": 250}, "createdAt": 1708000002000}
    conn.execute(
        "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
        ("bubbleId:abc-123:b1", json.dumps(bubble1).encode()),
    )
    conn.execute(
        "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
        ("bubbleId:abc-123:b2", json.dumps(bubble2).encode()),
    )

    # Insert a cursorAuth entry
    conn.execute(
        "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
        ("cursorAuth/cachedEmail", "user@example.com"),
    )

    conn.commit()
    conn.close()
    return db_path


class TestDecompress:
    def test_passthrough_non_zlib(self):
        data = b"hello world"
        assert _decompress(data) == data

    def test_decompresses_zlib(self):
        original = b"test data for compression"
        compressed = zlib.compress(original)
        assert _decompress(compressed) == original

    def test_empty_bytes(self):
        assert _decompress(b"") == b""


class TestParseJson:
    def test_parses_plain_json(self):
        data = json.dumps({"key": "value"}).encode()
        assert _parse_json(data) == {"key": "value"}

    def test_parses_compressed_json(self):
        original = json.dumps({"compressed": True}).encode()
        compressed = zlib.compress(original)
        assert _parse_json(compressed) == {"compressed": True}

    def test_returns_none_for_invalid(self):
        assert _parse_json(b"not json") is None

    def test_returns_none_for_empty(self):
        assert _parse_json(b"") is None


class TestReadItemTable:
    def test_reads_existing_key(self, vscdb_path: str):
        result = read_item_table(vscdb_path, "cursorAuth/cachedEmail")
        assert result == "user@example.com"

    def test_returns_none_for_missing_key(self, vscdb_path: str):
        result = read_item_table(vscdb_path, "nonexistent")
        assert result is None

    def test_returns_none_for_missing_file(self):
        result = read_item_table("/nonexistent/path.vscdb", "key")
        assert result is None


class TestIterSessions:
    def test_yields_session(self, vscdb_path: str):
        sessions = list(iter_sessions(vscdb_path))
        assert len(sessions) == 1
        s = sessions[0]
        assert s.composer_id == "abc-123"
        assert s.composer_data["createdAt"] == 1708000000000
        assert s.db_path == vscdb_path

    def test_loads_bubble_entries(self, vscdb_path: str):
        sessions = list(iter_sessions(vscdb_path))
        s = sessions[0]
        assert "bubbleId:abc-123:b1" in s.bubble_entries
        assert s.bubble_entries["bubbleId:abc-123:b1"]["tokenCount"]["inputTokens"] == 100

    def test_empty_db(self, tmp_path: Path):
        db_path = str(tmp_path / "empty.vscdb")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        conn.commit()
        conn.close()
        assert list(iter_sessions(db_path)) == []

    def test_compressed_composer_data(self, tmp_path: Path):
        db_path = str(tmp_path / "compressed.vscdb")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        composer_data = {"createdAt": 1708000000000, "conversation": []}
        compressed = zlib.compress(json.dumps(composer_data).encode())
        conn.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            ("composerData:zlib-test", compressed),
        )
        conn.commit()
        conn.close()

        sessions = list(iter_sessions(db_path))
        assert len(sessions) == 1
        assert sessions[0].composer_id == "zlib-test"


class TestScanSessionTimestamps:
    def test_returns_timestamps(self, vscdb_path: str):
        result = scan_session_timestamps(vscdb_path)
        assert "abc-123" in result
        assert result["abc-123"] == 1708000000000  # createdAt as fallback

    def test_prefers_last_updated_at(self, tmp_path: Path):
        db_path = str(tmp_path / "updated.vscdb")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        cd = {"createdAt": 1000, "lastUpdatedAt": 2000, "conversation": []}
        conn.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            ("composerData:s1", json.dumps(cd).encode()),
        )
        conn.commit()
        conn.close()
        result = scan_session_timestamps(db_path)
        assert result["s1"] == 2000

    def test_empty_db(self, tmp_path: Path):
        db_path = str(tmp_path / "empty.vscdb")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        conn.commit()
        conn.close()
        assert scan_session_timestamps(db_path) == {}

    def test_missing_file(self):
        assert scan_session_timestamps("/nonexistent/path.vscdb") == {}


class TestLoadSession:
    def test_loads_existing_session(self, vscdb_path: str):
        session = load_session(vscdb_path, "abc-123")
        assert session is not None
        assert session.composer_id == "abc-123"
        assert session.composer_data["createdAt"] == 1708000000000
        assert "bubbleId:abc-123:b1" in session.bubble_entries

    def test_returns_none_for_missing(self, vscdb_path: str):
        assert load_session(vscdb_path, "nonexistent") is None

    def test_returns_none_for_missing_file(self):
        assert load_session("/nonexistent/path.vscdb", "x") is None

    def test_loads_agent_kv_from_conversation_state(self, tmp_path: Path):
        db_path = str(tmp_path / "agentkv.vscdb")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        fake_hash = "a" * 64
        cd = {
            "createdAt": 1000,
            "conversation": [],
            "conversationState": {"someKey": fake_hash},
        }
        conn.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            ("composerData:s1", json.dumps(cd).encode()),
        )
        conn.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            (f"agentKv:blob:{fake_hash}", b"blob-data"),
        )
        conn.commit()
        conn.close()
        session = load_session(db_path, "s1")
        assert session is not None
        assert f"agentKv:blob:{fake_hash}" in session.agent_kv_entries


    def test_loads_agent_kv_from_string_conversation_state(self, tmp_path: Path):
        """String conversationState (base64 protobuf) should load agentKv blobs."""

        db_path = str(tmp_path / "string_state.vscdb")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value BLOB)")

        # Build a protobuf with two 32-byte hashes
        hash1 = b"\x01" * 32
        hash2 = b"\x02" * 32
        proto = bytes([0x0a, 0x20]) + hash1 + bytes([0x0a, 0x20]) + hash2
        conv_state = base64.b64encode(proto).decode()

        cd = {
            "createdAt": 1000,
            "conversation": [],
            "conversationState": conv_state,
        }
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            ("composerData:s1", json.dumps(cd).encode()),
        )
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            (f"agentKv:blob:{hash1.hex()}", b"blob-data-1"),
        )
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            (f"agentKv:blob:{hash2.hex()}", b"blob-data-2"),
        )
        conn.commit()
        conn.close()

        session = load_session(db_path, "s1")
        assert session is not None
        assert len(session.agent_kv_entries) == 2
        assert session.agent_kv_entries[f"agentKv:blob:{hash1.hex()}"] == b"blob-data-1"
        assert session.agent_kv_entries[f"agentKv:blob:{hash2.hex()}"] == b"blob-data-2"


class TestMultipleSessions:
    def test_yields_multiple_sessions(self, tmp_path: Path):
        db_path = str(tmp_path / "multi.vscdb")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")

        for i in range(3):
            cd = {"createdAt": 1708000000000 + i * 1000, "conversation": []}
            conn.execute(
                "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
                (f"composerData:session-{i}", json.dumps(cd).encode()),
            )
        conn.commit()
        conn.close()

        sessions = list(iter_sessions(db_path))
        assert len(sessions) == 3
        ids = {s.composer_id for s in sessions}
        assert ids == {"session-0", "session-1", "session-2"}
