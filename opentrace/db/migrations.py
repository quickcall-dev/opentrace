# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Schema version tracking and migration support."""


from pathlib import Path

from psycopg import AsyncConnection


CURRENT_SCHEMA_VERSION = 1


async def get_schema_version(conn: AsyncConnection) -> int | None:
    """Return the current schema version, or None if the table doesn't exist."""
    result = await conn.execute(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.tables "
        "  WHERE table_name = 'schema_version'"
        ")"
    )
    row = await result.fetchone()
    if not row or not row[0]:
        return None

    result = await conn.execute("SELECT MAX(version) FROM schema_version")
    row = await result.fetchone()
    return row[0] if row else None


def _read_schema_sql() -> str:
    """Read the schema.sql file bundled with the package."""
    schema_path = Path(__file__).parent / "schema.sql"
    return schema_path.read_text()


async def ensure_schema(conn: AsyncConnection) -> int:
    """Apply the schema if not present. Returns the current version."""
    version = await get_schema_version(conn)
    if version is None:
        sql = _read_schema_sql()
        await conn.execute(sql)
        await conn.commit()
        return CURRENT_SCHEMA_VERSION
    return version
