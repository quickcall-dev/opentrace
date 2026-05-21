# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for the auth module (KeyRole, get_key_role, load_auth_keys)."""


import os
from unittest.mock import patch



from opentrace.server.auth import KeyRole, get_key_role, load_auth_keys


class TestGetKeyRole:
    def test_auth_disabled_when_both_sets_empty(self):
        """When no keys configured, everything is ADMIN (auth disabled)."""
        assert get_key_role(None, set(), set()) == KeyRole.ADMIN
        assert get_key_role("random_key", set(), set()) == KeyRole.ADMIN

    def test_admin_key(self):
        admin = {"admin_abc123"}
        push = {"push_xyz789"}
        assert get_key_role("admin_abc123", admin, push) == KeyRole.ADMIN

    def test_push_key(self):
        admin = {"admin_abc123"}
        push = {"push_xyz789"}
        assert get_key_role("push_xyz789", admin, push) == KeyRole.PUSH

    def test_unknown_key(self):
        admin = {"admin_abc123"}
        push = {"push_xyz789"}
        assert get_key_role("unknown_key", admin, push) == KeyRole.NONE

    def test_no_key_provided(self):
        admin = {"admin_abc123"}
        push = {"push_xyz789"}
        assert get_key_role(None, admin, push) == KeyRole.NONE
        assert get_key_role("", admin, push) == KeyRole.NONE

    def test_key_in_both_sets_is_admin(self):
        """If a key is in both sets, admin wins (checked first)."""
        both = {"shared_key"}
        assert get_key_role("shared_key", both, both) == KeyRole.ADMIN

    def test_only_admin_keys(self):
        admin = {"admin_abc123"}
        assert get_key_role("admin_abc123", admin, set()) == KeyRole.ADMIN
        assert get_key_role(None, admin, set()) == KeyRole.NONE

    def test_only_push_keys(self):
        push = {"push_xyz789"}
        assert get_key_role("push_xyz789", set(), push) == KeyRole.PUSH
        assert get_key_role(None, set(), push) == KeyRole.NONE


class TestLoadAuthKeys:
    def test_reads_admin_and_push_env_vars(self):
        env = {
            "QUICKCALL_OPENTRACE_ADMIN_KEYS": "admin_a,admin_b",
            "QUICKCALL_OPENTRACE_PUSH_KEYS": "push_x,push_y",
        }
        with patch.dict(os.environ, env, clear=False):
            admin, push = load_auth_keys()
        assert admin == {"admin_a", "admin_b"}
        assert push == {"push_x", "push_y"}

    def test_legacy_api_keys_go_to_push_set(self):
        env = {"QUICKCALL_OPENTRACE_API_KEYS": "legacy_key1,legacy_key2"}
        with patch.dict(os.environ, env, clear=False):
            admin, push = load_auth_keys()
        assert admin == set()
        assert "legacy_key1" in push
        assert "legacy_key2" in push

    def test_empty_env_vars(self):
        env = {
            "QUICKCALL_OPENTRACE_ADMIN_KEYS": "",
            "QUICKCALL_OPENTRACE_PUSH_KEYS": "",
        }
        with patch.dict(os.environ, env, clear=False):
            admin, push = load_auth_keys()
        assert admin == set()
        assert push == set()

    def test_strips_whitespace(self):
        env = {"QUICKCALL_OPENTRACE_ADMIN_KEYS": " admin_a , admin_b "}
        with patch.dict(os.environ, env, clear=False):
            admin, _ = load_auth_keys()
        assert admin == {"admin_a", "admin_b"}

