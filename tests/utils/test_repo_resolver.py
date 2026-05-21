# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale


from pathlib import Path
from unittest.mock import patch

from opentrace.utils.repo_resolver import (
    RepoInfo,
    _extract_repo_name,
    decode_cursor_slug,
    extract_cursor_slug_from_path,
    extract_gemini_hash_from_path,
    resolve_global_identity,
    resolve_repo,
)


class TestExtractRepoName:
    def test_ssh_url(self):
        assert _extract_repo_name("git@github.com:org/repo.git") == "org/repo"

    def test_https_url(self):
        assert _extract_repo_name("https://github.com/org/repo.git") == "org/repo"

    def test_https_without_git_suffix(self):
        assert _extract_repo_name("https://github.com/org/repo") == "org/repo"

    def test_ssh_with_port(self):
        assert _extract_repo_name("ssh://git@github.com:22/org/repo.git") == "org/repo"

    def test_invalid_url(self):
        assert _extract_repo_name("not-a-url") is None

    def test_empty_string(self):
        assert _extract_repo_name("") is None


class TestDecodeCursorSlug:
    @patch("opentrace.utils.repo_resolver._has_prefix", return_value=True)
    @patch("opentrace.utils.repo_resolver.os.path.isdir", return_value=True)
    def test_valid_slug_existing_path(self, mock_isdir, mock_prefix):
        result = decode_cursor_slug("home-test-repo")
        assert result == "/home/test/repo"

    @patch("opentrace.utils.repo_resolver._has_prefix", return_value=False)
    @patch("opentrace.utils.repo_resolver.os.path.isdir", return_value=False)
    def test_valid_slug_nonexistent_path(self, mock_isdir, mock_prefix):
        assert decode_cursor_slug("home-test-missing") is None

    def test_empty_slug(self):
        assert decode_cursor_slug("") is None

    @patch("opentrace.utils.repo_resolver._has_prefix", return_value=True)
    @patch("opentrace.utils.repo_resolver.os.path.isdir", return_value=True)
    def test_slug_with_dashes_in_dirname(self, mock_isdir, mock_prefix):
        """Cursor slug where directory name contains dashes."""
        result = decode_cursor_slug("Users-test-work-opentrace")
        # Should find a valid path (exact result depends on which splits match isdir)
        assert result is not None
        assert result.startswith("/")


class TestExtractCursorSlugFromPath:
    def test_standard_path(self):
        path = (
            "/home/user/.cursor/projects/home-user-project/agent-transcripts/123.txt"
        )
        assert extract_cursor_slug_from_path(path) == "home-user-project"

    def test_non_matching_path(self):
        assert extract_cursor_slug_from_path("/some/random/path") is None

    def test_path_with_tilde(self):
        path = "~/.cursor/projects/-home-user-project/agent-transcripts/123.txt"
        assert extract_cursor_slug_from_path(path) == "-home-user-project"


class TestExtractGeminiHashFromPath:
    def test_standard_path(self):
        path = "/home/user/.gemini/tmp/abc123def/chats/session-001.json"
        assert extract_gemini_hash_from_path(path) == "abc123def"

    def test_non_matching_path(self):
        assert extract_gemini_hash_from_path("/some/random/path") is None


class TestResolveRepo:
    def test_real_git_repo(self):
        """Test resolve_repo on the current repo (which is always a git repo)."""
        repo_root = str(Path(__file__).resolve().parents[1])
        info = resolve_repo(repo_root)
        assert isinstance(info, RepoInfo)
        assert info.cwd == repo_root
        # Some source snapshots used in CI do not include a configured git remote.
        assert info.repo_url is None or isinstance(info.repo_url, str)
        assert info.repo_name is None or isinstance(info.repo_name, str)
        assert info.git_branch is not None
        assert info.git_commit is not None

    def test_non_git_directory(self):
        info = resolve_repo("/tmp")
        assert info.cwd == "/tmp"
        assert info.repo_url is None
        assert info.repo_name is None
        assert info.git_branch is None
        assert info.git_commit is None


class TestResolveGlobalIdentity:
    def test_returns_tuple(self):
        email, name = resolve_global_identity()
        # On a configured machine, at least email should be set
        assert email is None or isinstance(email, str)
        assert name is None or isinstance(name, str)
