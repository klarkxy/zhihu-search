"""This repository no longer ships a DeepSeek Harness plugin."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_HOME = "https://github.com/klarkxy/dsh-plugins/tree/main/plugins/dsh-zhihu"
RETIRED_INSTALL = 'dsh plugin --profile web add "github:klarkxy/zhihu-search"'


def test_repository_no_longer_ships_a_dsh_bundle() -> None:
    assert not (ROOT / "package.json").exists()
    assert not (ROOT / "dsh-plugin").exists()


def test_documentation_points_dsh_users_to_dsh_plugins() -> None:
    for path in (
        ROOT / "README.md",
        ROOT / "AGENT_SETUP.md",
        ROOT / "setup" / "README.md",
        ROOT / "setup" / "dsh.md",
        ROOT / "skills" / "zhihu-search" / "references" / "setup.md",
    ):
        content = path.read_text(encoding="utf-8")
        assert "@klarkxy/dsh-zhihu" in content
        assert PLUGIN_HOME in content
        assert RETIRED_INSTALL not in content
        assert "dsh-plugin topic" not in content


def test_documentation_describes_mcp_capability_profiles() -> None:
    markers = ("knowledge", "user", "questions", "creator", "office", "full")
    for path in (
        ROOT / "README.md",
        ROOT / "AGENT_SETUP.md",
        ROOT / "docs" / "API_COVERAGE.md",
        ROOT / "setup" / "README.md",
        ROOT / "setup" / "codex.md",
        ROOT / "setup" / "claude-code.md",
        ROOT / "setup" / "opencode.md",
        ROOT / "setup" / "hanako-agent.md",
        ROOT / "skills" / "zhihu-search" / "SKILL.md",
        ROOT / "skills" / "zhihu-search" / "references" / "setup.md",
    ):
        content = path.read_text(encoding="utf-8")
        missing = [name for name in markers if name not in content]
        assert not missing, f"{path.name} missing MCP profiles: {missing}"
