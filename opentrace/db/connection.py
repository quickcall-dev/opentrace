# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Async connection pool wrapper around psycopg3."""


import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool


DEFAULT_DSN = "postgresql://quickcall:quickcall@localhost:5432/quickcall"


class ConnectionPool:
    """Thin wrapper around psycopg_pool.AsyncConnectionPool.

    Usage::

        pool = ConnectionPool()
        await pool.open()
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
        await pool.close()
    """

    def __init__(
        self,
        dsn: str | None = None,
        min_size: int = 2,
        max_size: int = 10,
    ) -> None:
        self._dsn = dsn or os.environ.get("QUICKCALL_OPENTRACE_DSN", DEFAULT_DSN)
        self._pool = AsyncConnectionPool(
            conninfo=self._dsn,
            min_size=min_size,
            max_size=max_size,
            open=False,
        )

    async def open(self) -> None:
        await self._pool.open()

    async def close(self) -> None:
        await self._pool.close()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection]:
        async with self._pool.connection() as conn:
            yield conn

    async def __aenter__(self) -> "ConnectionPool":
        await self.open()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
