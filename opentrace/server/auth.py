# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""API key authentication for the ingest server.

Two-tier auth: admin keys (full read/write) and push keys (write-only).
Keys are loaded from QUICKCALL_OPENTRACE_ADMIN_KEYS and QUICKCALL_OPENTRACE_PUSH_KEYS env vars
(comma-separated), with backwards compat for QUICKCALL_OPENTRACE_API_KEYS and config.json.
"""


import enum
import logging
import os

logger = logging.getLogger(__name__)


class KeyRole(enum.Enum):
    """Role granted by an API key."""

    ADMIN = "admin"
    PUSH = "push"
    NONE = "none"


def load_auth_keys() -> tuple[set[str], set[str]]:
    """Load admin and push key sets from env vars / config.

    Returns (admin_keys, push_keys).
    """
    admin_keys: set[str] = set()
    push_keys: set[str] = set()

    # New env vars
    for raw in os.environ.get("QUICKCALL_OPENTRACE_ADMIN_KEYS", "").split(","):
        k = raw.strip()
        if k:
            admin_keys.add(k)

    for raw in os.environ.get("QUICKCALL_OPENTRACE_PUSH_KEYS", "").split(","):
        k = raw.strip()
        if k:
            push_keys.add(k)

    # Legacy env var → push set
    for raw in os.environ.get("QUICKCALL_OPENTRACE_API_KEYS", "").split(","):
        k = raw.strip()
        if k:
            push_keys.add(k)

    return admin_keys, push_keys


def get_key_role(
    key: str | None,
    admin_keys: set[str],
    push_keys: set[str],
) -> KeyRole:
    """Determine the role for a given API key.

    If both sets are empty, auth is disabled → ADMIN (allow everything).
    """
    if not admin_keys and not push_keys:
        return KeyRole.ADMIN  # auth disabled
    if not key:
        return KeyRole.NONE
    if key in admin_keys:
        return KeyRole.ADMIN
    if key in push_keys:
        return KeyRole.PUSH
    return KeyRole.NONE


def load_api_keys() -> set[str]:
    """Load all API keys (admin + push) as a flat set. Deprecated."""
    admin_keys, push_keys = load_auth_keys()
    return admin_keys | push_keys


def validate_api_key(key: str | None, allowed_keys: set[str]) -> bool:
    """Check if the provided key is in the allowlist. Deprecated."""
    if not allowed_keys:
        return True
    if not key:
        return False
    return key in allowed_keys

