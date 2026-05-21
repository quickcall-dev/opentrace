# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Database infrastructure for quickcall-opentrace daemon.

Provides async connection pooling, batch writing via COPY,
and schema migration support for PostgreSQL.
"""

from opentrace.db.connection import ConnectionPool
from opentrace.db.writer import BatchWriter
from opentrace.db.migrations import ensure_schema

__all__ = ["ConnectionPool", "BatchWriter", "ensure_schema"]
