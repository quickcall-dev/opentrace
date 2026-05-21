# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""HTTP pusher with retry queue and exponential backoff."""


import json
import logging
import time
import traceback
import urllib.error
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass, field

from opentrace.daemon.config import DaemonConfig
from opentrace.daemon.push_status import record_error
from opentrace.schemas.unified import NormalizedMessage

logger = logging.getLogger("quickcall.pusher")

# Azure TLS termination drops connections on large POST bodies, causing
# SSL EOF errors in Python's urllib.  Cap payload size well below the
# server's 10 MB hard limit so each request completes reliably.
_MAX_PAYLOAD_BYTES = 4 * 1024 * 1024  # 4 MB


def _serialize_message(msg: NormalizedMessage) -> dict:
    """Serialize a NormalizedMessage to a JSON-compatible dict."""
    d = asdict(msg)
    # Remove None values for cleaner payloads
    return {k: v for k, v in d.items() if v is not None}


@dataclass
class Pusher:
    """Pushes NormalizedMessages to the ingest server with retry logic."""

    config: DaemonConfig
    _queue: deque[dict] = field(default_factory=deque, repr=False)
    _backoff: float = field(default=0.0, repr=False)
    _last_failure_time: float = field(default=0.0, repr=False)
    _consecutive_failures: int = field(default=0, repr=False)

    def push(self, messages: list[NormalizedMessage]) -> bool:
        """Push messages to ingest server. Returns True on success."""
        if not messages:
            return True

        # Respect backoff before attempting push
        if self._backoff > 0:
            # Decay backoff if enough time has passed since last failure
            if self._last_failure_time > 0:
                since_last = time.monotonic() - self._last_failure_time
                if since_last > self.config.retry_cooldown:
                    self._backoff = self.config.retry_backoff_base
                    self._consecutive_failures = 1
                    logger.info("Backoff decayed after %.0fs cooldown", since_last)
            time.sleep(self._backoff)

        serialized = [_serialize_message(m) for m in messages]
        success = self._post_batch(serialized)

        if success:
            self._on_success()
            self._drain_queue()
            return True
        else:
            self._enqueue(serialized)
            return False

    def _auth_headers(self) -> dict[str, str]:
        """Build headers dict, including X-API-Key if configured."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["X-API-Key"] = self.config.api_key
        return headers

    def _post_batch(self, batch: list[dict]) -> bool:
        """HTTP POST a batch to the ingest endpoint.

        If the JSON payload exceeds _MAX_PAYLOAD_BYTES the batch is split
        in half and each half is sent separately.  The server's upsert
        semantics make partial-success safe (caller re-enqueues on False).
        """
        payload = json.dumps(batch).encode("utf-8")

        if len(payload) > _MAX_PAYLOAD_BYTES and len(batch) > 1:
            mid = len(batch) // 2
            logger.debug(
                "Splitting oversized payload (%d bytes, %d msgs) into two batches",
                len(payload), len(batch),
            )
            return self._post_batch(batch[:mid]) and self._post_batch(batch[mid:])

        req = urllib.request.Request(
            self.config.ingest_url,
            data=payload,
            headers=self._auth_headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status < 300:
                    return True
                logger.warning("Ingest server returned %d", resp.status)
                return False
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            self._on_failure(e)
            return False

    def _enqueue(self, batch: list[dict]) -> None:
        """Add failed batch to retry queue, dropping oldest if full."""
        dropped = 0
        for item in batch:
            if len(self._queue) >= self.config.retry_queue_max:
                self._queue.popleft()
                dropped += 1
            self._queue.append(item)
        if dropped:
            logger.warning(
                "Retry queue full — dropped %d oldest message(s)", dropped
            )

    def _drain_queue(self) -> None:
        """Try to send queued messages after a successful push."""
        while self._queue:
            batch: list[dict] = []
            while self._queue and len(batch) < self.config.batch_size:
                batch.append(self._queue.popleft())

            if batch:
                if not self._post_batch(batch):
                    # Re-enqueue at the front and stop draining
                    for item in reversed(batch):
                        self._queue.appendleft(item)
                    break

    def _on_success(self) -> None:
        """Reset backoff state on success."""
        self._backoff = 0.0
        self._consecutive_failures = 0
        self._last_failure_time = 0.0

    def _on_failure(self, error: Exception) -> None:
        """Handle a push failure with backoff tracking."""
        now = time.monotonic()
        self._consecutive_failures += 1

        # Only record after 3+ consecutive failures to filter transient blips
        if self._consecutive_failures >= 3:
            tb_text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            record_error(str(error), traceback_text=tb_text)

        if self._last_failure_time == 0.0:
            self._last_failure_time = now

        # Calculate backoff
        self._backoff = min(
            self.config.retry_backoff_base * (2 ** (self._consecutive_failures - 1)),
            self.config.retry_backoff_max,
        )

        elapsed = now - self._last_failure_time
        if elapsed > self.config.retry_timeout:
            logger.error(
                "Persistent push failure for %.0fs: %s. Continuing to collect.",
                elapsed,
                error,
            )
            # Drop queue on persistent failure to prevent memory bloat
            if len(self._queue) >= self.config.retry_queue_max:
                dropped = len(self._queue)
                self._queue.clear()
                logger.warning("Dropped %d queued messages after persistent failure", dropped)
        else:
            logger.warning(
                "Push failed (attempt %d, backoff %.1fs): %s",
                self._consecutive_failures,
                self._backoff,
                error,
            )

    def report_progress_bulk(self, reports: list[dict]) -> bool:
        """POST bulk file progress to /api/file-progress-bulk. Returns True on success."""
        if not reports:
            return True
        url = self.config.ingest_url.replace("/ingest", "/api/file-progress-bulk")
        payload = json.dumps(reports).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers=self._auth_headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status < 300
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            logger.warning("Failed to report bulk file progress: %s", e)
            return False

    @property
    def current_backoff(self) -> float:
        """Current backoff delay in seconds."""
        return self._backoff

    @property
    def queue_size(self) -> int:
        """Number of messages in retry queue."""
        return len(self._queue)

    def has_queued(self) -> bool:
        """Whether there are queued messages waiting to be sent."""
        return len(self._queue) > 0
