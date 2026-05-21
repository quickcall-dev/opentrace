# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for resolve_repo TTL cache."""

from unittest.mock import patch

import pytest

from opentrace.utils.repo_resolver import clear_repo_cache, resolve_repo, _repo_cache, _REPO_CACHE_TTL


@pytest.fixture(autouse=True)
def clean_cache():
    """Clear repo cache before each test."""
    clear_repo_cache()
    yield
    clear_repo_cache()


class TestRepoCache:
    def test_cache_hit_avoids_subprocess(self):
        """Second call with same cwd should use cache, not spawn git."""
        with patch("opentrace.utils.repo_resolver._git_cmd") as mock_git:
            mock_git.return_value = None
            resolve_repo("/tmp/test-repo")
            assert mock_git.call_count == 5  # remote, branch, commit, email, name

            # Second call should hit cache
            resolve_repo("/tmp/test-repo")
            assert mock_git.call_count == 5  # no additional calls

    def test_different_cwds_are_cached_separately(self):
        """Different cwds should have independent cache entries."""
        with patch("opentrace.utils.repo_resolver._git_cmd") as mock_git:
            mock_git.return_value = None
            resolve_repo("/tmp/repo-a")
            resolve_repo("/tmp/repo-b")
            assert mock_git.call_count == 10  # 5 per cwd

    def test_cache_expires_after_ttl(self):
        """Cache should expire after TTL."""
        with patch("opentrace.utils.repo_resolver._git_cmd") as mock_git:
            mock_git.return_value = None
            resolve_repo("/tmp/test-repo")
            assert mock_git.call_count == 5

            # Manually expire cache
            cwd = "/tmp/test-repo"
            cached_time, info = _repo_cache[cwd]
            _repo_cache[cwd] = (cached_time - _REPO_CACHE_TTL - 1, info)

            resolve_repo("/tmp/test-repo")
            assert mock_git.call_count == 10  # re-resolved

    def test_clear_repo_cache(self):
        """clear_repo_cache should empty the cache."""
        with patch("opentrace.utils.repo_resolver._git_cmd", return_value=None):
            resolve_repo("/tmp/test-repo")
            assert len(_repo_cache) == 1
            clear_repo_cache()
            assert len(_repo_cache) == 0

    def test_cached_result_has_correct_fields(self):
        """Cached RepoInfo should preserve all resolved fields."""
        with patch("opentrace.utils.repo_resolver._git_cmd") as mock_git:
            mock_git.side_effect = [
                "git@github.com:org/repo.git",  # remote
                "main",                           # branch
                "abc123",                         # commit
                "user@example.com",               # email
                "Test User",                      # name
            ]
            info = resolve_repo("/tmp/test-repo")
            assert info.repo_url == "git@github.com:org/repo.git"
            assert info.git_branch == "main"
            assert info.git_commit == "abc123"
            assert info.user_email == "user@example.com"
            assert info.user_name == "Test User"
            assert info.repo_name == "org/repo"

            # Cached version should be identical
            info2 = resolve_repo("/tmp/test-repo")
            assert info2.repo_url == info.repo_url
            assert info2.git_branch == info.git_branch
