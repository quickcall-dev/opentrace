# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""HTTP request handlers for the ingest server.

Provides handlers for:
- POST /ingest  — Accept NormalizedMessage JSON arrays
- POST /sessions — Upsert a session record
- GET  /health  — Health check with DB connectivity status
"""


import json
import logging
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlparse

from opentrace.db.connection import ConnectionPool
from opentrace.db.reader import get_feed, get_file_sync_state, get_messages, get_orgs, get_sessions, get_stats
from opentrace.db.writer import SESSION_UPSERT_SQL
from opentrace.schemas.unified import (
    NormalizedMessage,
    SessionContext,
    TokenUsage,
    ToolCall,
    ToolResult,
)
from opentrace.server.batch import BatchAccumulator

logger = logging.getLogger(__name__)

# Org slug → UUID cache (loaded on first use, refreshed periodically)
_org_cache: dict[str, str] = {}
_org_cache_loaded = False


async def _load_org_cache(pool: ConnectionPool) -> None:
    """Load orgs table into memory cache."""
    global _org_cache, _org_cache_loaded
    try:
        async with pool.connection() as conn:
            result = await conn.execute("SELECT slug, id FROM orgs")
            rows = await result.fetchall()
            _org_cache = {row[0]: str(row[1]) for row in rows}
            _org_cache_loaded = True
            logger.info("Org cache loaded: %d orgs", len(_org_cache))
    except Exception:
        logger.exception("Failed to load org cache")


def _resolve_org_id(org_slug: str | None) -> str | None:
    """Resolve org slug to UUID from cache. Returns None if not found."""
    if not org_slug or not _org_cache:
        return None
    return _org_cache.get(org_slug)


def _json_response(data: dict[str, Any]) -> tuple[bytes, int]:
    """Serialize a dict to JSON bytes and return with status 200."""
    return json.dumps(data).encode(), HTTPStatus.OK


def _error_response(
    message: str, status: int = HTTPStatus.BAD_REQUEST
) -> tuple[bytes, int]:
    return json.dumps({"error": message}).encode(), status


def _parse_token_usage(data: dict | None) -> TokenUsage:
    if not data:
        return TokenUsage()
    return TokenUsage(
        input=data.get("input", 0),
        output=data.get("output", 0),
        cached=data.get("cached", 0),
        thinking=data.get("thinking", 0),
    )


def _parse_tool_call(data: dict | None) -> ToolCall | None:
    if not data:
        return None
    return ToolCall(
        id=data["id"],
        name=data["name"],
        input=data.get("input", {}),
    )


def _parse_tool_result(data: dict | None) -> ToolResult | None:
    if not data:
        return None
    output = data.get("output", "")
    if not isinstance(output, str):
        output = json.dumps(output)
    return ToolResult(
        call_id=data["call_id"],
        output=output,
        status=data.get("status", "success"),
    )


def _parse_session_context(data: dict | None) -> SessionContext | None:
    if not data:
        return None
    return SessionContext(
        **{k: v for k, v in data.items() if k in SessionContext.__dataclass_fields__}
    )


def _dict_to_normalized_message(d: dict[str, Any]) -> NormalizedMessage:
    """Convert a JSON dict into a NormalizedMessage dataclass."""
    return NormalizedMessage(
        id=d["id"],
        session_id=d["session_id"],
        source=d["source"],
        source_schema_version=d.get("source_schema_version", 1),
        msg_type=d["msg_type"],
        timestamp=d.get("timestamp", ""),
        content=d.get("content") if isinstance(d.get("content"), str) else (json.dumps(d["content"]) if d.get("content") is not None else None),
        tokens=_parse_token_usage(d.get("tokens")),
        tool_call=_parse_tool_call(d.get("tool_call")),
        tool_result=_parse_tool_result(d.get("tool_result")),
        thinking=d.get("thinking"),
        model=d.get("model"),
        session_context=_parse_session_context(d.get("session_context")),
        raw_data=d.get("raw_data"),
        raw_file_path=d.get("raw_file_path", ""),
        raw_line_number=d.get("raw_line_number"),
    )


REQUIRED_MESSAGE_FIELDS = {"id", "session_id", "source", "msg_type"}

FILE_PROGRESS_UPSERT_SQL = (
    "INSERT INTO file_progress (raw_file_path, source, last_line_read, content_hash, updated_at) "
    "VALUES (%s, %s, %s, %s, NOW()) "
    "ON CONFLICT (raw_file_path, source) DO UPDATE SET "
    "last_line_read = EXCLUDED.last_line_read, "
    "content_hash = EXCLUDED.content_hash, "
    "updated_at = NOW()"
)


def _validate_message_dict(d: dict[str, Any]) -> str | None:
    """Return an error string if the dict is missing required fields."""
    missing = REQUIRED_MESSAGE_FIELDS - d.keys()
    if missing:
        return f"Missing required fields: {', '.join(sorted(missing))}"
    return None


async def handle_ingest(
    body: bytes, accumulator: BatchAccumulator
) -> tuple[bytes, int]:
    """Handle POST /ingest — accept a JSON array of NormalizedMessage dicts."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        return _error_response(f"Invalid JSON: {e}")

    if not isinstance(payload, list):
        return _error_response("Request body must be a JSON array")

    if not payload:
        return _json_response({"ingested": 0})

    messages: list[NormalizedMessage] = []
    for i, item in enumerate(payload):
        if not isinstance(item, dict):
            return _error_response(f"Item {i} is not a JSON object")
        err = _validate_message_dict(item)
        if err:
            return _error_response(f"Item {i}: {err}")
        try:
            messages.append(_dict_to_normalized_message(item))
        except (KeyError, TypeError) as e:
            return _error_response(f"Item {i}: {e}")

    count = await accumulator.add(messages)
    return _json_response({"ingested": count})


REQUIRED_SESSION_FIELDS = {"id", "source"}


async def handle_sessions(
    body: bytes, pool: ConnectionPool
) -> tuple[bytes, int]:
    """Handle POST /sessions — upsert a session record."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        return _error_response(f"Invalid JSON: {e}")

    if not isinstance(payload, dict):
        return _error_response("Request body must be a JSON object")

    missing = REQUIRED_SESSION_FIELDS - payload.keys()
    if missing:
        return _error_response(f"Missing required fields: {', '.join(sorted(missing))}")

    org_id = _resolve_org_id(payload.get("org"))

    try:
        async with pool.connection() as conn:
            await conn.execute(
                SESSION_UPSERT_SQL,
                (
                    payload["id"],
                    payload["source"],
                    payload.get("model"),
                    payload.get("user_email"),
                    payload.get("user_name"),
                    payload.get("device_name"),
                    payload.get("device_id"),
                    payload.get("cwd"),
                    payload.get("repo_url"),
                    payload.get("repo_name"),
                    payload.get("git_branch"),
                    payload.get("git_commit"),
                    payload.get("project_hash"),
                    payload.get("org"),
                    payload.get("raw_file_path"),
                    org_id,
                ),
            )
            await conn.commit()
    except Exception:
        logger.exception("Failed to upsert session")
        return _error_response(
            "Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR
        )

    return _json_response({"ok": True})


async def handle_health(pool: ConnectionPool) -> tuple[bytes, int]:
    """Handle GET /health — check database connectivity."""
    try:
        async with pool.connection() as conn:
            result = await conn.execute("SELECT 1")
            await result.fetchone()
        return _json_response({"status": "ok", "db": "connected"})
    except Exception:
        logger.exception("Health check: DB unreachable")
        return json.dumps(
            {"status": "degraded", "db": "disconnected"}
        ).encode(), HTTPStatus.SERVICE_UNAVAILABLE


# --- Dashboard read endpoints ---


def _parse_qs(path: str) -> dict[str, str]:
    """Parse query string from a path like /api/sessions?source=claude_code."""
    parsed = urlparse(path)
    qs = parse_qs(parsed.query)
    return {k: v[0] for k, v in qs.items()}


MAX_LIMIT = 500


def _clamp_int(value: str, default: int, min_val: int = 0, max_val: int = MAX_LIMIT) -> int:
    """Parse and clamp an integer query param to [min_val, max_val]."""
    try:
        n = int(value)
    except (ValueError, TypeError):
        return default
    return max(min_val, min(n, max_val))


def _serialize_row(row: dict) -> dict:
    """Make a DB row JSON-serializable (handle datetime, etc.)."""
    out = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


async def handle_api_stats(
    pool: ConnectionPool, path: str
) -> tuple[bytes, int]:
    """GET /api/stats — aggregate dashboard stats."""
    qs = _parse_qs(path)
    try:
        async with pool.connection() as conn:
            data = await get_stats(conn, org=qs.get("org"))
        data["by_source"] = [_serialize_row(r) for r in data["by_source"]]
        data["by_type"] = [_serialize_row(r) for r in data["by_type"]]
        data["tokens"] = _serialize_row(data["tokens"])
        return _json_response(data)
    except Exception:
        logger.exception("Failed to get stats")
        return _error_response("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)


async def handle_api_sessions(
    pool: ConnectionPool, path: str
) -> tuple[bytes, int]:
    """GET /api/sessions — list sessions with message counts."""
    qs = _parse_qs(path)
    try:
        async with pool.connection() as conn:
            rows = await get_sessions(
                conn,
                source=qs.get("source"),
                session_id=qs.get("id"),
                org=qs.get("org"),
                date=qs.get("date"),
                limit=_clamp_int(qs.get("limit", "50"), 50),
                offset=_clamp_int(qs.get("offset", "0"), 0),
            )
        return _json_response([_serialize_row(r) for r in rows])
    except Exception:
        logger.exception("Failed to get sessions")
        return _error_response("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)


async def handle_api_messages(
    pool: ConnectionPool, path: str
) -> tuple[bytes, int]:
    """GET /api/messages — messages for a session."""
    qs = _parse_qs(path)
    session_id = qs.get("session_id")
    if not session_id:
        return _error_response("Missing required query parameter: session_id")
    try:
        async with pool.connection() as conn:
            rows = await get_messages(
                conn,
                session_id=session_id,
                limit=_clamp_int(qs.get("limit", "100"), 100),
                offset=_clamp_int(qs.get("offset", "0"), 0),
            )
        return _json_response([_serialize_row(r) for r in rows])
    except Exception:
        logger.exception("Failed to get messages")
        return _error_response("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)


async def handle_file_progress(
    body: bytes, pool: ConnectionPool
) -> tuple[bytes, int]:
    """Handle POST /api/file-progress — upsert daemon's read position for a file."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        return _error_response(f"Invalid JSON: {e}")

    if not isinstance(payload, dict):
        return _error_response("Request body must be a JSON object")

    required = {"raw_file_path", "source", "last_line_read"}
    missing = required - payload.keys()
    if missing:
        return _error_response(f"Missing required fields: {', '.join(sorted(missing))}")

    try:
        async with pool.connection() as conn:
            await conn.execute(
                FILE_PROGRESS_UPSERT_SQL,
                (
                    payload["raw_file_path"],
                    payload["source"],
                    payload["last_line_read"],
                    payload.get("content_hash"),
                ),
            )
            await conn.commit()
    except Exception:
        logger.exception("Failed to upsert file progress")
        return _error_response(
            "Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR
        )

    return _json_response({"ok": True})


async def handle_api_sync(pool: ConnectionPool) -> tuple[bytes, int]:
    """GET /api/sync — file sync state for daemon reconciliation."""
    try:
        async with pool.connection() as conn:
            rows = await get_file_sync_state(conn)
        return _json_response([_serialize_row(r) for r in rows])
    except Exception:
        logger.exception("Failed to get sync state")
        return _error_response("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)


async def handle_api_orgs(pool: ConnectionPool) -> tuple[bytes, int]:
    """GET /api/orgs — distinct org values."""
    try:
        async with pool.connection() as conn:
            orgs = await get_orgs(conn)
        return json.dumps(orgs).encode(), HTTPStatus.OK
    except Exception:
        logger.exception("Failed to get orgs")
        return _error_response("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)


async def handle_api_monitor(
    pool: ConnectionPool, accumulator: BatchAccumulator
) -> tuple[bytes, int]:
    """GET /api/monitor — real-time server ingestion health."""
    try:
        acc_stats = accumulator.stats

        # DB counts
        db_stats = {"total_sessions": 0, "total_messages": 0}
        try:
            async with pool.connection() as conn:
                data = await get_stats(conn)
                db_stats["total_sessions"] = data.get("total_sessions", 0)
                db_stats["total_messages"] = data.get("total_messages", 0)
        except Exception:
            logger.exception("Monitor: failed to get DB stats")

        # Determine status
        batch_acc = acc_stats["batch_accumulator"]
        recent = acc_stats["recent_ingestion"]
        if batch_acc["flush_failures"] > 0 or batch_acc["total_dropped"] > 0:
            status = "degraded"
        elif recent["messages_last_1m"] > 0:
            status = "receiving"
        else:
            status = "idle"

        result = {
            "batch_accumulator": batch_acc,
            "recent_ingestion": recent,
            "database": db_stats,
            "status": status,
        }
        return _json_response(result)
    except Exception:
        logger.exception("Failed to get monitor data")
        return _error_response("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)


async def handle_file_progress_bulk(
    body: bytes, pool: ConnectionPool
) -> tuple[bytes, int]:
    """Handle POST /api/file-progress-bulk — batch upsert daemon read positions."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        return _error_response(f"Invalid JSON: {e}")

    if not isinstance(payload, list):
        return _error_response("Request body must be a JSON array")

    if not payload:
        return _json_response({"ok": True, "updated": 0})

    required = {"raw_file_path", "source", "last_line_read"}
    for i, item in enumerate(payload):
        if not isinstance(item, dict):
            return _error_response(f"Item {i} is not a JSON object")
        missing = required - item.keys()
        if missing:
            return _error_response(f"Item {i}: missing fields: {', '.join(sorted(missing))}")

    try:
        async with pool.connection() as conn:
            for item in payload:
                await conn.execute(
                    FILE_PROGRESS_UPSERT_SQL,
                    (
                        item["raw_file_path"],
                        item["source"],
                        item["last_line_read"],
                        item.get("content_hash"),
                    ),
                )
            await conn.commit()
    except Exception:
        logger.exception("Failed to bulk upsert file progress")
        return _error_response(
            "Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR
        )

    return _json_response({"ok": True, "updated": len(payload)})


async def handle_api_feed(
    pool: ConnectionPool, path: str
) -> tuple[bytes, int]:
    """GET /api/feed — latest messages across all sessions."""
    qs = _parse_qs(path)
    try:
        async with pool.connection() as conn:
            rows = await get_feed(
                conn,
                since=qs.get("since"),
                org=qs.get("org"),
                limit=_clamp_int(qs.get("limit", "20"), 20),
            )
        return _json_response([_serialize_row(r) for r in rows])
    except Exception:
        logger.exception("Failed to get feed")
        return _error_response("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)
