# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for db.connection module (C4)."""


import os
from unittest.mock import patch


from opentrace.db.connection import DEFAULT_DSN, ConnectionPool


class TestConnectionPoolInit:
    def test_default_dsn(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("QUICKCALL_OPENTRACE_DSN", None)
            pool = ConnectionPool()
            assert pool._dsn == DEFAULT_DSN

    def test_explicit_dsn(self):
        pool = ConnectionPool(dsn="postgresql://custom:pass@host/db")
        assert pool._dsn == "postgresql://custom:pass@host/db"

    def test_env_var_dsn(self):
        with patch.dict(os.environ, {"QUICKCALL_OPENTRACE_DSN": "postgresql://env:pass@host/db"}):
            pool = ConnectionPool()
            assert pool._dsn == "postgresql://env:pass@host/db"

    def test_explicit_dsn_takes_priority_over_env(self):
        with patch.dict(os.environ, {"QUICKCALL_OPENTRACE_DSN": "postgresql://env/db"}):
            pool = ConnectionPool(dsn="postgresql://explicit/db")
            assert pool._dsn == "postgresql://explicit/db"

    def test_default_pool_sizes(self):
        pool = ConnectionPool()
        assert pool._pool.min_size == 2
        assert pool._pool.max_size == 10

    def test_custom_pool_sizes(self):
        pool = ConnectionPool(min_size=1, max_size=5)
        assert pool._pool.min_size == 1
        assert pool._pool.max_size == 5
