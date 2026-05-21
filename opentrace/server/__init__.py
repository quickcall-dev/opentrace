# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""HTTP ingest server for quickcall-opentrace.

Accepts NormalizedMessage batches over HTTP and writes to PostgreSQL.
"""

from opentrace.server.app import create_server, run_server
from opentrace.server.batch import BatchAccumulator

__all__ = ["create_server", "run_server", "BatchAccumulator"]
