# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Batch accumulator for NormalizedMessage ingestion.

Accumulates messages and flushes when either:
- 100 messages have been collected, or
- 5 seconds have elapsed since the first message in the batch
"""


import asyncio
import logging
import time
from collections import deque
from typing import Callable, Awaitable, Sequence

from opentrace.schemas.unified import NormalizedMessage

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 100
DEFAULT_FLUSH_INTERVAL = 5.0
DEFAULT_MAX_BUFFER_SIZE = 10_000
MAX_FLUSH_RETRIES = 3


class BatchAccumulator:
    """Thread-safe batch accumulator with size and time-based flushing.

    Parameters:
        flush_callback: Async function called with a list of messages to persist.
        batch_size: Max messages before triggering a flush.
        flush_interval: Max seconds before triggering a time-based flush.
        max_buffer_size: Max messages to hold in memory. Excess are dropped.
    """

    def __init__(
        self,
        flush_callback: Callable[[Sequence[NormalizedMessage]], Awaitable[int]],
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
        max_buffer_size: int = DEFAULT_MAX_BUFFER_SIZE,
    ) -> None:
        self._flush_callback = flush_callback
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_buffer_size = max_buffer_size
        self._buffer: list[NormalizedMessage] = []
        self._lock = asyncio.Lock()
        self._timer_task: asyncio.Task | None = None
        self._closed = False
        self._total_flushed = 0
        self._total_dropped = 0
        self._flush_failures = 0
        self._last_flush_at: float = 0.0
        self._recent_flushes: deque[tuple[float, int]] = deque()

    @property
    def pending(self) -> int:
        return len(self._buffer)

    @property
    def total_flushed(self) -> int:
        return self._total_flushed

    @property
    def stats(self) -> dict:
        """Return a snapshot of accumulator metrics for monitoring."""
        now = time.time()
        # Trim stale entries
        cutoff_5m = now - 300
        while self._recent_flushes and self._recent_flushes[0][0] < cutoff_5m:
            self._recent_flushes.popleft()

        messages_last_5m = sum(count for _, count in self._recent_flushes)
        cutoff_1m = now - 60
        messages_last_1m = sum(
            count for ts, count in self._recent_flushes if ts >= cutoff_1m
        )

        idle_seconds = (now - self._last_flush_at) if self._last_flush_at else None

        return {
            "batch_accumulator": {
                "pending": self.pending,
                "total_flushed": self._total_flushed,
                "total_dropped": self._total_dropped,
                "flush_failures": self._flush_failures,
            },
            "recent_ingestion": {
                "messages_last_1m": messages_last_1m,
                "messages_last_5m": messages_last_5m,
                "last_flush_at": self._last_flush_at or None,
                "idle_seconds": round(idle_seconds, 1) if idle_seconds is not None else None,
            },
        }

    async def add(self, messages: Sequence[NormalizedMessage]) -> int:
        """Add messages to the buffer. Returns count added.

        Triggers an immediate flush if the buffer reaches batch_size.
        """
        if self._closed:
            raise RuntimeError("BatchAccumulator is closed")

        added = 0
        async with self._lock:
            self._buffer.extend(messages)
            added = len(messages)

            if self._timer_task is None and self._buffer:
                self._timer_task = asyncio.create_task(self._timer_flush())

            if len(self._buffer) >= self._batch_size:
                await self._flush_locked()

        return added

    async def flush(self) -> int:
        """Force a flush of the current buffer. Returns count flushed."""
        async with self._lock:
            return await self._flush_locked()

    async def _flush_locked(self) -> int:
        """Flush while already holding the lock."""
        if not self._buffer:
            return 0

        batch = self._buffer[:]
        self._buffer.clear()
        self._cancel_timer()

        try:
            count = await self._flush_callback(batch)
            self._total_flushed += count
            self._flush_failures = 0
            now = time.time()
            self._last_flush_at = now
            self._recent_flushes.append((now, count))
            # Trim entries older than 5 minutes
            cutoff = now - 300
            while self._recent_flushes and self._recent_flushes[0][0] < cutoff:
                self._recent_flushes.popleft()
            logger.info("Flushed %d messages (total: %d)", count, self._total_flushed)
            return count
        except Exception:
            self._flush_failures += 1
            if self._flush_failures >= MAX_FLUSH_RETRIES:
                self._total_dropped += len(batch)
                logger.error(
                    "Flush failed %d times, dropping %d messages (total dropped: %d)",
                    self._flush_failures, len(batch), self._total_dropped,
                )
                self._flush_failures = 0
            else:
                # Re-queue, but cap buffer to prevent unbounded growth
                combined = batch + self._buffer
                if len(combined) > self._max_buffer_size:
                    overflow = len(combined) - self._max_buffer_size
                    self._total_dropped += overflow
                    logger.warning(
                        "Buffer overflow: dropping %d oldest messages (total dropped: %d)",
                        overflow, self._total_dropped,
                    )
                    combined = combined[overflow:]
                self._buffer = combined
                logger.exception(
                    "Flush failed (attempt %d/%d), re-queuing %d messages",
                    self._flush_failures, MAX_FLUSH_RETRIES, len(combined),
                )
            raise

    async def _timer_flush(self) -> None:
        """Wait for flush_interval then flush."""
        try:
            await asyncio.sleep(self._flush_interval)
            async with self._lock:
                self._timer_task = None
                await self._flush_locked()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Timer flush failed")
            self._timer_task = None

    def _cancel_timer(self) -> None:
        if self._timer_task is not None and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = None

    async def close(self) -> int:
        """Flush remaining messages and prevent further additions."""
        self._closed = True
        count = await self.flush()
        self._cancel_timer()
        return count
