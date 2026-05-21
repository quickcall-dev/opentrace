# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Reader for Cursor's state.vscdb (cursorDiskKV) SQLite databases.

Extracts composer sessions with their bubble entries and agent KV blobs
from the globalStorage/state.vscdb cursorDiskKV table.

Note on NULL values: Cursor uses SQLite's ON CONFLICT REPLACE for its KV tables.
When sessions are deleted or archived, Cursor writes NULL as the value rather than
deleting the row — the key remains as a tombstone. In real DBs ~4% of composerData
rows and ~16% of bubbleId rows have NULL values. All reader functions handle this
by skipping NULLs (there is no data to extract from a deleted session).
"""


import base64
import json
import re
import sqlite3
import zlib
from dataclasses import dataclass
from typing import Any, Iterator


_RE_LAST_UPDATED = re.compile(r'"lastUpdatedAt"\s*:\s*(\d+)')
_RE_CREATED_AT = re.compile(r'"createdAt"\s*:\s*(\d+)')


def _decompress_to_text(raw: bytes) -> str | None:
    """Decompress and decode to text without JSON parsing."""
    if raw is None:
        return None
    try:
        data = _decompress(raw)
        return data.decode("utf-8", errors="replace")
    except (UnicodeDecodeError, ValueError):
        return None


def _extract_timestamp(text: str | None) -> int:
    """Extract lastUpdatedAt or createdAt from raw JSON text via regex."""
    if not text:
        return 0
    m = _RE_LAST_UPDATED.search(text)
    if not m:
        m = _RE_CREATED_AT.search(text)
    return int(m.group(1)) if m else 0


@dataclass
class VscdbSession:
    """A single composer session extracted from state.vscdb."""

    composer_id: str
    composer_data: dict[str, Any]
    bubble_entries: dict[str, dict[str, Any]]  # bubbleId:<cid>:<bid> → parsed JSON
    agent_kv_entries: dict[str, bytes]  # agentKv:blob:<hash> → raw bytes
    db_path: str


def iter_sessions(db_path: str) -> Iterator[VscdbSession]:
    """Yield VscdbSession objects for each composerData entry in the database.

    Reads all composerData:<id> rows, then for each composer ID loads
    the corresponding bubbleId:<cid>:* rows. Agent KV blobs are loaded
    once and shared across sessions (content-addressed).
    """
    # Load all composer data rows
    composer_rows = _read_kv_rows(db_path, "composerData:")
    if not composer_rows:
        return

    # Load all agent KV blobs (shared, content-addressed)
    agent_kv = _read_kv_rows(db_path, "agentKv:blob:")

    for key, raw in composer_rows.items():
        # key is "composerData:<composerId>"
        composer_id = key.removeprefix("composerData:")
        if not composer_id:
            continue

        # NULL values are tombstones for deleted/archived sessions — skip them
        parsed = _parse_json(raw)
        if parsed is None or not isinstance(parsed, dict):
            continue

        # Load bubble entries for this composer
        bubble_prefix = f"bubbleId:{composer_id}:"
        bubble_rows = _read_kv_rows(db_path, bubble_prefix)
        bubble_entries: dict[str, dict[str, Any]] = {}
        for bkey, braw in bubble_rows.items():
            bparsed = _parse_json(braw)
            if bparsed is not None and isinstance(bparsed, dict):
                bubble_entries[bkey] = bparsed

        yield VscdbSession(
            composer_id=composer_id,
            composer_data=parsed,
            bubble_entries=bubble_entries,
            agent_kv_entries=agent_kv,
            db_path=db_path,
        )


def scan_session_timestamps(db_path: str) -> dict[str, int]:
    """Quick-scan: return {composerId: lastUpdatedAt} without loading full session data.

    Reads composerData:* keys from cursorDiskKV, parses just enough JSON to extract
    lastUpdatedAt (or createdAt as fallback). Much faster than iter_sessions() since
    it doesn't load bubbles or agent KV blobs.
    """
    result: dict[str, int] = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            table = _resolve_table(conn)
            # Use json_extract to pull timestamps without fetching full
            # values (~172MB). Falls back to regex on full value if
            # json_extract is unavailable (old SQLite builds).
            try:
                cursor = conn.execute(
                    f"""SELECT key,
                        COALESCE(
                            json_extract(value, '$.lastUpdatedAt'),
                            json_extract(value, '$.createdAt'),
                            0
                        )
                    FROM {table}
                    WHERE key LIKE 'composerData:%'
                      AND value IS NOT NULL""",
                )
                for key, ts in cursor:
                    composer_id = key.removeprefix("composerData:")
                    if not composer_id:
                        continue
                    if isinstance(ts, (int, float)) and ts:
                        result[composer_id] = int(ts)
            except sqlite3.OperationalError:
                # json_extract not available — fall back to regex
                cursor = conn.execute(
                    f"SELECT key, value FROM {table}"
                    " WHERE key LIKE 'composerData:%'"
                    " AND value IS NOT NULL",
                )
                for key, val in cursor:
                    composer_id = key.removeprefix("composerData:")
                    if not composer_id:
                        continue
                    if isinstance(val, str):
                        text = val
                    else:
                        text = _decompress_to_text(val)
                    ts = _extract_timestamp(text)
                    if ts:
                        result[composer_id] = ts
                if ts:
                    result[composer_id] = ts
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        pass
    return result


def load_session(db_path: str, composer_id: str) -> VscdbSession | None:
    """Load a single session by composer ID.

    More efficient than iter_sessions() for incremental updates since it only
    reads the specific composerData, its bubbleId entries, and relevant agentKv blobs.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            table = _resolve_table(conn)

            # Load composer data
            row = conn.execute(
                f"SELECT value FROM {table} WHERE key = ?",
                (f"composerData:{composer_id}",),
            ).fetchone()
            if row is None:
                return None

            # NULL value = tombstone for deleted session
            val = row[0]
            if isinstance(val, str):
                val = val.encode("utf-8")
            parsed = _parse_json(val)
            if parsed is None or not isinstance(parsed, dict):
                return None

            # Load bubble entries (NULL bubble values are also tombstones — skipped by _parse_json)
            bubble_prefix = f"bubbleId:{composer_id}:"
            bubble_cursor = conn.execute(
                f"SELECT key, value FROM {table} WHERE key LIKE ? || '%'",
                (bubble_prefix,),
            )
            bubble_entries: dict[str, dict[str, Any]] = {}
            for bkey, braw in bubble_cursor:
                if isinstance(braw, str):
                    braw = braw.encode("utf-8")
                bparsed = _parse_json(braw)
                if bparsed is not None and isinstance(bparsed, dict):
                    bubble_entries[bkey] = bparsed

            # Load agent KV blobs referenced by conversationState hashes
            agent_kv_entries: dict[str, bytes] = {}
            conv_state = parsed.get("conversationState")
            hashes_to_load: list[str] = []
            if isinstance(conv_state, str) and conv_state:
                # Base64-encoded protobuf with embedded SHA-256 hashes
                hashes_to_load = _extract_hashes(conv_state)
            elif isinstance(conv_state, dict):
                # Legacy dict format with hash values
                for v in conv_state.values():
                    if isinstance(v, str) and len(v) == 64:
                        hashes_to_load.append(v)

            for h in hashes_to_load:
                agent_key = f"agentKv:blob:{h}"
                arow = conn.execute(
                    f"SELECT value FROM {table} WHERE key = ?",
                    (agent_key,),
                ).fetchone()
                if arow is not None:
                    aval = arow[0]
                    if isinstance(aval, str):
                        aval = aval.encode("utf-8")
                    agent_kv_entries[agent_key] = aval

            return VscdbSession(
                composer_id=composer_id,
                composer_data=parsed,
                bubble_entries=bubble_entries,
                agent_kv_entries=agent_kv_entries,
                db_path=db_path,
            )
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return None


def read_item_table(db_path: str, key: str) -> str | None:
    """Read a single key from the ItemTable and return as string.

    Returns None if the key doesn't exist or on any error.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            val = row[0]
            if isinstance(val, bytes):
                return _decompress(val).decode("utf-8", errors="replace")
            return str(val)
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return None


def _read_kv_rows(db_path: str, prefix: str) -> dict[str, bytes]:
    """Read all rows from cursorDiskKV whose key starts with prefix.

    Falls back to ItemTable if cursorDiskKV doesn't exist.
    Returns {key: raw_value_bytes} dict.
    """
    result: dict[str, bytes] = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            table = _resolve_table(conn)
            cursor = conn.execute(
                f"SELECT key, value FROM {table} WHERE key LIKE ? || '%'",
                (prefix,),
            )
            for key, val in cursor:
                # Skip NULL tombstones (deleted sessions/bubbles)
                if val is None:
                    continue
                if isinstance(val, str):
                    val = val.encode("utf-8")
                result[key] = val
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        pass
    return result


def _resolve_table(conn: sqlite3.Connection) -> str:
    """Return 'cursorDiskKV' if it exists and has data, else 'ItemTable'."""
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'"
        ).fetchone()
        if row:
            return "cursorDiskKV"
    except sqlite3.Error:
        pass
    return "ItemTable"


def _decompress(raw: bytes) -> bytes:
    """Decompress bytes if zlib-compressed (0x78 0x9c header), otherwise return as-is."""
    if len(raw) >= 2 and raw[0] == 0x78 and raw[1] in (0x01, 0x5E, 0x9C, 0xDA):
        try:
            return zlib.decompress(raw)
        except zlib.error:
            pass
    return raw


def _extract_hashes(conversation_state: str) -> list[str]:
    """Extract SHA-256 hashes from a base64-encoded protobuf conversation state.

    Format: optional leading '~', then base64 data.
    Walk the protobuf wire format looking for length-delimited fields of exactly 32 bytes.
    """
    if not conversation_state:
        return []

    data_str = conversation_state.lstrip("~")
    if not data_str:
        return []

    padding = 4 - (len(data_str) % 4)
    if padding < 4:
        data_str += "=" * padding

    try:
        data = base64.b64decode(data_str)
    except Exception:
        return []

    return _walk_protobuf_for_hashes(data)


def _walk_protobuf_for_hashes(data: bytes) -> list[str]:
    """Walk protobuf wire format and extract 32-byte length-delimited fields as hex hashes."""
    hashes: list[str] = []
    pos = 0
    length = len(data)

    while pos < length:
        try:
            tag, pos = _decode_varint(data, pos)
        except (IndexError, ValueError):
            break

        wire_type = tag & 0x07

        if wire_type == 0:  # varint
            try:
                _, pos = _decode_varint(data, pos)
            except (IndexError, ValueError):
                break
        elif wire_type == 2:  # length-delimited
            try:
                field_len, pos = _decode_varint(data, pos)
            except (IndexError, ValueError):
                break
            if pos + field_len > length:
                break
            if field_len == 32:
                hash_bytes = data[pos : pos + 32]
                hashes.append(hash_bytes.hex())
            pos += field_len
        elif wire_type == 5:  # 32-bit fixed
            pos += 4
        elif wire_type == 1:  # 64-bit fixed
            pos += 8
        else:
            break

    return hashes


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a protobuf varint starting at pos. Returns (value, new_pos)."""
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise IndexError("Varint extends beyond data")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
        if shift >= 64:
            raise ValueError("Varint too long")
    return result, pos


def _parse_json(raw: bytes | None) -> Any | None:
    """Decompress (if needed) and parse JSON. Returns None on failure or NULL input.

    NULL values occur for tombstoned (deleted/archived) rows in cursorDiskKV.
    """
    if raw is None:
        return None
    try:
        data = _decompress(raw)
        text = data.decode("utf-8", errors="replace")
        return json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
