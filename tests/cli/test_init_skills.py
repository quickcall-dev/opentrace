# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Tests for AGENTS.md and CLAUDE.md wiring in init_skills."""


from pathlib import Path

from opentrace.cli.init_skills import ensure_agents_md, wire_claude_md


class TestEnsureAgentsMd:
    def test_creates_agents_md_when_missing(self, tmp_path: Path) -> None:
        result = ensure_agents_md(tmp_path)
        assert result is True
        content = (tmp_path / "AGENTS.md").read_text()
        assert "<!-- opentrace:rules-start -->" in content
        assert "<!-- opentrace:rules-end -->" in content
        assert "# AGENTS.md" in content

    def test_adds_sentinels_to_existing(self, tmp_path: Path) -> None:
        agents = tmp_path / "AGENTS.md"
        agents.write_text("# My Project Rules\n\nSome existing content.\n")
        result = ensure_agents_md(tmp_path)
        assert result is True
        content = agents.read_text()
        assert "<!-- opentrace:rules-start -->" in content
        assert "<!-- opentrace:rules-end -->" in content

    def test_noop_when_sentinels_exist(self, tmp_path: Path) -> None:
        agents = tmp_path / "AGENTS.md"
        original = "# AGENTS.md\n\n<!-- opentrace:rules-start -->\n<!-- opentrace:rules-end -->\n"
        agents.write_text(original)
        result = ensure_agents_md(tmp_path)
        assert result is False
        assert agents.read_text() == original

    def test_preserves_existing_content(self, tmp_path: Path) -> None:
        agents = tmp_path / "AGENTS.md"
        existing = "# My Rules\n\n- Rule one\n- Rule two\n"
        agents.write_text(existing)
        ensure_agents_md(tmp_path)
        content = agents.read_text()
        assert content.startswith(existing)
        assert "<!-- opentrace:rules-start -->" in content


class TestWireClaudeMd:
    def test_adds_import_when_claude_md_exists(self, tmp_path: Path) -> None:
        claude = tmp_path / "CLAUDE.md"
        claude.write_text("# CLAUDE.md\n\nSome instructions.\n")
        result = wire_claude_md(tmp_path)
        assert result is True
        content = claude.read_text()
        assert "@AGENTS.md" in content

    def test_noop_when_already_referenced(self, tmp_path: Path) -> None:
        claude = tmp_path / "CLAUDE.md"
        original = "# CLAUDE.md\n\n@AGENTS.md\n"
        claude.write_text(original)
        result = wire_claude_md(tmp_path)
        assert result is False

    def test_noop_when_no_claude_md(self, tmp_path: Path) -> None:
        result = wire_claude_md(tmp_path)
        assert result is False

    def test_case_insensitive_detection(self, tmp_path: Path) -> None:
        claude = tmp_path / "CLAUDE.md"
        claude.write_text("# CLAUDE.md\n\nSee agents.md for rules.\n")
        result = wire_claude_md(tmp_path)
        assert result is False
