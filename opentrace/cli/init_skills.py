# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Project instruction-file helpers for QuickCall OpenTrace."""


from pathlib import Path

_AGENTS_MD_SENTINEL_START = "<!-- opentrace:rules-start -->"
_AGENTS_MD_SENTINEL_END = "<!-- opentrace:rules-end -->"


def ensure_agents_md(project_dir: Path) -> bool:
    agents = project_dir / "AGENTS.md"
    if not agents.exists():
        agents.write_text(
            f"# AGENTS.md\n\n{_AGENTS_MD_SENTINEL_START}\n{_AGENTS_MD_SENTINEL_END}\n"
        )
        return True
    content = agents.read_text()
    if _AGENTS_MD_SENTINEL_START in content and _AGENTS_MD_SENTINEL_END in content:
        return False
    agents.write_text(
        content + f"\n\n{_AGENTS_MD_SENTINEL_START}\n{_AGENTS_MD_SENTINEL_END}\n"
    )
    return True


def wire_claude_md(project_dir: Path) -> bool:
    claude = project_dir / "CLAUDE.md"
    if not claude.exists():
        return False
    content = claude.read_text()
    lowered = content.lower()
    if "@agents.md" in lowered or "agents.md" in lowered:
        return False
    claude.write_text(content.rstrip() + "\n\n@AGENTS.md\n")
    return True
