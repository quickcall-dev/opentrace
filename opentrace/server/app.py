# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""HTTP ingest server using stdlib http.server.

Runs on localhost:19777 by default (configurable via QUICKCALL_OPENTRACE_PORT env var).
Uses an asyncio event loop for database operations while serving HTTP
requests synchronously.
"""


import asyncio
import json
import logging
import os
import signal
import threading
from http import HTTPStatus
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Sequence

from opentrace.db.connection import ConnectionPool
from opentrace.db.migrations import ensure_schema
from opentrace.db.writer import BatchWriter
from opentrace.schemas.unified import NormalizedMessage
from opentrace.server.auth import (
    KeyRole,
    get_key_role,
    load_auth_keys,
)
from opentrace.server.batch import BatchAccumulator
from opentrace.server.handlers import (
    _load_org_cache,
    handle_api_feed,
    handle_api_messages,
    handle_api_monitor,
    handle_api_orgs,
    handle_api_sessions,
    handle_api_stats,
    handle_api_sync,
    handle_file_progress,
    handle_file_progress_bulk,
    handle_health,
    handle_ingest,
    handle_sessions,
)

logger = logging.getLogger(__name__)

DEFAULT_HOST = os.environ.get("QUICKCALL_OPENTRACE_HOST", "localhost")
DEFAULT_PORT = int(os.environ.get("QUICKCALL_OPENTRACE_PORT", "19777"))
MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB


class IngestHandler(BaseHTTPRequestHandler):
    """Routes HTTP requests to async handler functions."""

    pool: ConnectionPool
    accumulator: BatchAccumulator
    loop: asyncio.AbstractEventLoop
    admin_keys: set[str]
    push_keys: set[str]
    def log_message(self, format: str, *args: object) -> None:
        logger.info(format, *args)

    def _read_body(self) -> bytes | None:
        """Read request body, enforcing MAX_BODY_SIZE. Returns None if too large."""
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY_SIZE:
            return None
        return self.rfile.read(length) if length > 0 else b""

    def _send_json(self, body: bytes, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        """Handle OPTIONS requests."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-API-Key, X-User-Email",
        )
        self.send_header("Access-Control-Max-Age", "3600")
        self.end_headers()

    def _get_role(self) -> KeyRole:
        """Determine the caller's role from the X-API-Key header."""
        key = self.headers.get("X-API-Key")
        return get_key_role(key, self.admin_keys, self.push_keys)

    def _send_unauthorized(self) -> None:
        self._send_json(
            json.dumps({"error": "Unauthorized"}).encode(),
            HTTPStatus.UNAUTHORIZED,
        )

    def _run_async(self, coro):
        """Run an async coroutine from the sync handler (thread-safe)."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=30)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        # Public endpoints (no auth required)
        if path == "/health":
            body, status = self._run_async(handle_health(self.pool))
            self._send_json(body, status)
            return

        role = self._get_role()

        # Push-or-admin endpoints
        if path == "/api/sync":
            if role == KeyRole.NONE:
                self._send_unauthorized()
                return
            body, status = self._run_async(handle_api_sync(self.pool))
            self._send_json(body, status)
            return

        # Admin-only endpoints
        if role != KeyRole.ADMIN:
            self._send_unauthorized()
            return

        if path == "/api/monitor":
            body, status = self._run_async(
                handle_api_monitor(self.pool, self.accumulator)
            )
        elif path == "/api/orgs":
            body, status = self._run_async(handle_api_orgs(self.pool))
        elif path == "/api/stats":
            body, status = self._run_async(handle_api_stats(self.pool, self.path))
        elif path == "/api/sessions":
            body, status = self._run_async(
                handle_api_sessions(self.pool, self.path)
            )
        elif path == "/api/messages":
            body, status = self._run_async(
                handle_api_messages(self.pool, self.path)
            )
        elif path == "/api/feed":
            body, status = self._run_async(
                handle_api_feed(self.pool, self.path)
            )
        else:
            body = json.dumps({"error": "Not found"}).encode()
            status = HTTPStatus.NOT_FOUND

        self._send_json(body, status)

    def do_POST(self) -> None:
        role = self._get_role()

        # POST endpoints require PUSH or ADMIN
        if role == KeyRole.NONE:
            self._send_unauthorized()
            return

        raw_body = self._read_body()
        if raw_body is None:
            self._send_json(
                json.dumps({"error": "Payload too large"}).encode(),
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return

        if self.path == "/ingest":
            body, status = self._run_async(
                handle_ingest(raw_body, self.accumulator)
            )
            self._send_json(body, status)
        elif self.path == "/sessions":
            body, status = self._run_async(
                handle_sessions(raw_body, self.pool)
            )
            self._send_json(body, status)
        elif self.path == "/api/file-progress":
            body, status = self._run_async(
                handle_file_progress(raw_body, self.pool)
            )
            self._send_json(body, status)
        elif self.path == "/api/file-progress-bulk":
            body, status = self._run_async(
                handle_file_progress_bulk(raw_body, self.pool)
            )
            self._send_json(body, status)
        else:
            self._send_json(
                json.dumps({"error": "Not found"}).encode(),
                HTTPStatus.NOT_FOUND,
            )


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTPServer that handles each request in a new thread."""
    daemon_threads = True


def create_server(
    pool: ConnectionPool,
    accumulator: BatchAccumulator,
    loop: asyncio.AbstractEventLoop,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    admin_keys: set[str] | None = None,
    push_keys: set[str] | None = None,
) -> ThreadedHTTPServer:
    """Create and configure the HTTP server (does not start it)."""
    IngestHandler.pool = pool
    IngestHandler.accumulator = accumulator
    IngestHandler.loop = loop
    IngestHandler.admin_keys = admin_keys or set()
    IngestHandler.push_keys = push_keys or set()

    server = ThreadedHTTPServer((host, port), IngestHandler)
    total_keys = len(IngestHandler.admin_keys) + len(IngestHandler.push_keys)
    if total_keys:
        logger.info(
            "Ingest server configured on %s:%d (auth enabled, %d admin + %d push key(s))",
            host, port, len(IngestHandler.admin_keys), len(IngestHandler.push_keys),
        )
    else:
        logger.warning(
            "Ingest server configured on %s:%d (NO AUTH — set QUICKCALL_OPENTRACE_ADMIN_KEYS / QUICKCALL_OPENTRACE_PUSH_KEYS to enable)",
            host, port,
        )
    return server


def run_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    dsn: str | None = None,
) -> None:
    """Start the ingest server (blocking)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    loop = asyncio.new_event_loop()

    pool = ConnectionPool(dsn=dsn)
    loop.run_until_complete(pool.open())
    logger.info("Connection pool opened")

    # Ensure DB schema is up to date
    async def _init_schema():
        async with pool.connection() as conn:
            await ensure_schema(conn)

    loop.run_until_complete(_init_schema())
    logger.info("Database schema verified")

    # Load org slug→UUID cache into memory
    loop.run_until_complete(_load_org_cache(pool))

    # Build flush callback
    async def flush_to_db(messages: Sequence[NormalizedMessage]) -> int:
        async with pool.connection() as conn:
            writer = BatchWriter(conn)
            return await writer.write(messages)

    accumulator = BatchAccumulator(flush_callback=flush_to_db)

    admin_keys, push_keys = load_auth_keys()
    # Run event loop in a background thread so handler threads can
    # submit coroutines via run_coroutine_threadsafe.
    def _run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    loop_thread = threading.Thread(target=_run_loop, daemon=True, name="asyncio-loop")
    loop_thread.start()

    server = create_server(pool, accumulator, loop, host, port, admin_keys, push_keys)

    def _shutdown(signum, frame):
        logger.info("Shutting down...")
        server.shutdown()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Ingest server listening on %s:%d", host, port)
    try:
        server.serve_forever()
    finally:
        # Stop the async loop and clean up
        async def _cleanup():
            await accumulator.close()
            await pool.close()

        future = asyncio.run_coroutine_threadsafe(_cleanup(), loop)
        future.result(timeout=10)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        loop.close()
        logger.info("Server stopped")


if __name__ == "__main__":
    run_server()
