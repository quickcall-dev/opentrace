# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for db.migrations module (C5)."""


from pathlib import Path
from unittest.mock import AsyncMock


from opentrace.db.migrations import CURRENT_SCHEMA_VERSION, _read_schema_sql, ensure_schema, get_schema_version


class TestGetSchemaVersion:
    async def test_returns_none_when_table_missing(self):
        conn = AsyncMock()
        result_mock = AsyncMock()
        result_mock.fetchone = AsyncMock(return_value=(False,))
        conn.execute = AsyncMock(return_value=result_mock)

        version = await get_schema_version(conn)
        assert version is None

    async def test_returns_version_when_table_exists(self):
        conn = AsyncMock()
        # First call: table exists check
        exists_result = AsyncMock()
        exists_result.fetchone = AsyncMock(return_value=(True,))
        # Second call: get version
        version_result = AsyncMock()
        version_result.fetchone = AsyncMock(return_value=(2,))

        conn.execute = AsyncMock(side_effect=[exists_result, version_result])

        version = await get_schema_version(conn)
        assert version == 2

    async def test_returns_none_when_no_rows(self):
        conn = AsyncMock()
        exists_result = AsyncMock()
        exists_result.fetchone = AsyncMock(return_value=(True,))
        version_result = AsyncMock()
        version_result.fetchone = AsyncMock(return_value=None)

        conn.execute = AsyncMock(side_effect=[exists_result, version_result])

        version = await get_schema_version(conn)
        assert version is None


class TestReadSchemaSql:
    def test_reads_schema_file(self):
        sql = _read_schema_sql()
        assert isinstance(sql, str)
        assert len(sql) > 0
        assert "CREATE" in sql.upper() or "TABLE" in sql.upper()

    def test_schema_file_exists(self):
        schema_path = Path(__file__).parent.parent.parent / "opentrace" / "db" / "schema.sql"
        assert schema_path.exists()


class TestEnsureSchema:
    async def test_applies_schema_when_version_is_none(self):
        conn = AsyncMock()
        # get_schema_version returns None (table doesn't exist)
        exists_result = AsyncMock()
        exists_result.fetchone = AsyncMock(return_value=(False,))
        conn.execute = AsyncMock(return_value=exists_result)
        conn.commit = AsyncMock()

        version = await ensure_schema(conn)
        assert version == CURRENT_SCHEMA_VERSION
        conn.commit.assert_called_once()

    async def test_skips_when_version_is_current(self):
        conn = AsyncMock()
        exists_result = AsyncMock()
        exists_result.fetchone = AsyncMock(return_value=(True,))
        version_result = AsyncMock()
        version_result.fetchone = AsyncMock(return_value=(CURRENT_SCHEMA_VERSION,))

        conn.execute = AsyncMock(side_effect=[exists_result, version_result])
        conn.commit = AsyncMock()

        version = await ensure_schema(conn)
        assert version == CURRENT_SCHEMA_VERSION
        conn.commit.assert_not_called()
