# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Shared test fixtures and helpers (M4, L7)."""


from pathlib import Path


from opentrace.schemas.unified import NormalizedMessage

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def make_message(**kwargs) -> NormalizedMessage:
    """Create a NormalizedMessage with sensible defaults.

    Override any field by passing keyword arguments.
    """
    defaults = dict(
        id="msg-1",
        session_id="sess-1",
        source="claude_code",
        source_schema_version=1,
        msg_type="user",
        timestamp="2026-02-06T10:00:00Z",
        content="hello",
        raw_file_path="/tmp/test.jsonl",
    )
    defaults.update(kwargs)
    return NormalizedMessage(**defaults)
