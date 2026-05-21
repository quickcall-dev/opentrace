# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for daemon heartbeat diagnostics."""

from unittest.mock import MagicMock, patch

from opentrace.daemon.diagnostics import build_source_diagnostics, _diagnose_cursor_vscdb


class TestBuildSourceDiagnostics:
    """Test the top-level diagnostics builder."""

    def test_returns_cursor_vscdb_section(self):
        config = MagicMock()
        config.cursor_vscdb_glob = "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
        result = build_source_diagnostics(config)
        assert "cursor_vscdb" in result
        assert isinstance(result["cursor_vscdb"], dict)

    def test_never_raises_even_on_broken_config(self):
        """build_source_diagnostics must return {} on any exception, never raise."""
        config = MagicMock()
        # Force _diagnose_cursor_vscdb to blow up
        config.cursor_vscdb_glob = None  # os.path.join(str, None) → TypeError
        result = build_source_diagnostics(config)
        assert result == {}


class TestDiagnoseCursorVscdb:
    """Test the cursor vscdb path diagnostics."""

    @patch("glob.glob", return_value=[])
    @patch("opentrace.daemon.diagnostics.os.stat", side_effect=FileNotFoundError)
    @patch("opentrace.daemon.diagnostics.os.path.exists", return_value=False)
    @patch("opentrace.daemon.diagnostics.os.access", return_value=False)
    def test_missing_file_reports_not_found(self, mock_access, mock_exists, mock_stat, mock_glob):
        """When the vscdb file doesn't exist, all checks should report absent."""
        config = MagicMock()
        config.cursor_vscdb_glob = "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
        result = _diagnose_cursor_vscdb(config)

        assert result["file_exists"] is False
        assert result["file_readable"] is False
        assert result["file_size"] is None
        assert result["sqlite_ok"] is False
        assert result["glob_result_count"] == 0
        # Every path_walk entry should show not exists
        for entry in result["path_walk"]:
            assert entry["exists"] is False
            assert entry["readable"] is False

    @patch("glob.glob", return_value=["/mock/path/state.vscdb"])
    @patch("opentrace.daemon.diagnostics.sqlite3.connect")
    @patch("opentrace.daemon.diagnostics.os.access", return_value=True)
    @patch("opentrace.daemon.diagnostics.os.path.exists", return_value=True)
    @patch("opentrace.daemon.diagnostics.os.stat")
    def test_healthy_file_reports_all_ok(self, mock_stat, mock_exists, mock_access, mock_sqlite, mock_glob):
        """When everything is accessible, diagnostics should report healthy."""
        mock_stat.return_value = MagicMock(st_size=500_000_000)
        mock_conn = MagicMock()
        mock_sqlite.return_value = mock_conn

        config = MagicMock()
        config.cursor_vscdb_glob = "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
        result = _diagnose_cursor_vscdb(config)

        assert result["file_exists"] is True
        assert result["file_readable"] is True
        assert result["file_size"] == 500_000_000
        assert result["sqlite_ok"] is True
        assert result["glob_result_count"] == 1
        mock_conn.close.assert_called_once()
        # Every path_walk entry should show exists + readable
        for entry in result["path_walk"]:
            assert entry["exists"] is True
            assert entry["readable"] is True

    @patch("glob.glob", return_value=["/mock/path/state.vscdb"])
    @patch("opentrace.daemon.diagnostics.sqlite3.connect", side_effect=Exception("database is locked"))
    @patch("opentrace.daemon.diagnostics.os.access", return_value=True)
    @patch("opentrace.daemon.diagnostics.os.path.exists", return_value=True)
    @patch("opentrace.daemon.diagnostics.os.stat")
    def test_sqlite_failure_reported(self, mock_stat, mock_exists, mock_access, mock_sqlite, mock_glob):
        """File exists and readable but SQLite connect fails — should report sqlite_ok=False with error."""
        mock_stat.return_value = MagicMock(st_size=100)

        config = MagicMock()
        config.cursor_vscdb_glob = "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
        result = _diagnose_cursor_vscdb(config)

        assert result["file_exists"] is True
        assert result["file_readable"] is True
        assert result["sqlite_ok"] is False
        assert "database is locked" in result["sqlite_error"]

    @patch("glob.glob", return_value=[])
    @patch("opentrace.daemon.diagnostics.os.stat")
    @patch("opentrace.daemon.diagnostics.os.access")
    @patch("opentrace.daemon.diagnostics.os.path.exists")
    def test_permission_denied_midway(self, mock_exists, mock_access, mock_stat, mock_glob):
        """Directory exists but isn't readable — simulates TCC denial on macOS."""
        mock_stat.side_effect = FileNotFoundError  # file itself not reachable

        # First few dirs exist+readable, then one exists but not readable
        def exists_side_effect(path):
            return True  # all segments exist

        def access_side_effect(path, mode):
            if path.endswith("/Cursor"):
                return False  # ~/Library/Application Support/Cursor not readable
            return True

        mock_exists.side_effect = exists_side_effect
        mock_access.side_effect = access_side_effect

        config = MagicMock()
        config.cursor_vscdb_glob = "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
        result = _diagnose_cursor_vscdb(config)

        # Find the Cursor entry in path_walk — should show exists=True, readable=False
        cursor_entries = [e for e in result["path_walk"] if e["path"].endswith("Cursor")]
        assert len(cursor_entries) == 1
        assert cursor_entries[0]["exists"] is True
        assert cursor_entries[0]["readable"] is False

        # File itself shouldn't be found
        assert result["file_exists"] is False
        assert result["sqlite_ok"] is False

    def test_path_walk_covers_full_chain(self):
        """path_walk should include every directory from home down to the file."""
        config = MagicMock()
        config.cursor_vscdb_glob = "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
        result = _diagnose_cursor_vscdb(config)
        paths = [e["path"] for e in result["path_walk"]]
        # Should have entries for: ~, ~/Library, ~/Library/Application Support,
        # .../Cursor, .../User, .../globalStorage, .../state.vscdb
        assert len(paths) >= 7
        assert any("Library" in p and "Application" not in p for p in paths)
        assert any("globalStorage" in p for p in paths)
        assert any("state.vscdb" in p for p in paths)
