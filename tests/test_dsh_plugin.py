"""Validate the GitHub-installable DeepSeek Harness bundle contract."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "dsh-plugin"


def _project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as file:
        return tomllib.load(file)["project"]["version"]


def _manifest() -> dict[str, object]:
    return json.loads((ROOT / "package.json").read_text(encoding="utf-8"))


def _plugin_row() -> dict[str, object]:
    patch = yaml.safe_load(
        (PLUGIN_DIR / "cordis.patch.yml").read_text(encoding="utf-8")
    )
    assert isinstance(patch, list) and len(patch) == 1
    insert = patch[0]
    assert set(insert) == {"insert"}
    rows = insert["insert"]
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert isinstance(row, dict)
    return row


def test_dsh_bundle_manifest_is_git_installable_and_version_locked() -> None:
    manifest = _manifest()
    version = _project_version()

    assert manifest["name"] == "dsh-plugin-zhihu-search"
    assert manifest["version"] == version
    assert manifest["dsh"] == {
        "bundle": {"patch": "./dsh-plugin/cordis.patch.yml"}
    }
    assert set(manifest["files"]) == {
        "dsh-plugin/cordis.patch.yml",
        "dsh-plugin/README.md",
        "LICENSE",
    }
    assert "publishConfig" not in manifest
    assert manifest["repository"] == {
        "type": "git",
        "url": "git+https://github.com/klarkxy/zhihu-search.git",
    }
    assert manifest["engines"] == {"node": "^22.19.0 || >=24.0.0"}

    for filename in manifest["files"]:
        assert (ROOT / filename).is_file()


def test_dsh_bundle_uses_builtin_mcp_client_and_pinned_python_package() -> None:
    row = _plugin_row()
    version = _project_version()

    assert row["id"] == "zhihu-search-mcp"
    assert row["name"] == "@deepseek-ai/dsh-mcp-client"
    config = row["config"]
    assert config["serverName"] == "zhihu"
    assert config["transport"] == "stdio"
    assert config["command"] == "uvx"
    assert config["args"] == [
        "--from",
        f"zhihu-search=={version}",
        "zhihu-search",
        "serve",
        "--tools",
        "compact",
    ]
    assert config["toolCallTimeoutMs"] == 180000
    assert config["failOnStartupError"] is True
    assert config["reconnect"] == {
        "enabled": True,
        "initialDelayMs": 500,
        "maxDelayMs": 30000,
        "maxAttempts": 10,
    }


def test_dsh_bundle_contains_no_secret_or_install_script() -> None:
    manifest = _manifest()
    row = _plugin_row()
    serialized = json.dumps(row, ensure_ascii=False).lower()

    assert "scripts" not in manifest
    assert "dependencies" not in manifest
    assert "access_secret" not in serialized
    assert "oauth_token" not in serialized
    assert "env" not in row["config"]


def test_documentation_installs_the_github_repository() -> None:
    install_spec = '"github:klarkxy/zhihu-search"'
    pinned_spec = '"github:klarkxy/zhihu-search#<commit>"'

    for path in (
        ROOT / "README.md",
        ROOT / "setup" / "dsh.md",
        PLUGIN_DIR / "README.md",
    ):
        content = path.read_text(encoding="utf-8")
        assert install_spec in content

    assert pinned_spec in (ROOT / "setup" / "dsh.md").read_text(encoding="utf-8")
    assert pinned_spec in (PLUGIN_DIR / "README.md").read_text(encoding="utf-8")


def test_documentation_describes_mcp_capability_profiles() -> None:
    markers = ("knowledge", "user", "office", "full")
    for path in (
        ROOT / "README.md",
        ROOT / "AGENT_SETUP.md",
        ROOT / "docs" / "API_COVERAGE.md",
        ROOT / "setup" / "README.md",
        ROOT / "setup" / "codex.md",
        ROOT / "setup" / "claude-code.md",
        ROOT / "setup" / "opencode.md",
        ROOT / "setup" / "hanako-agent.md",
        ROOT / "setup" / "dsh.md",
        PLUGIN_DIR / "README.md",
        ROOT / "skills" / "zhihu-search" / "SKILL.md",
        ROOT / "skills" / "zhihu-search" / "references" / "setup.md",
    ):
        content = path.read_text(encoding="utf-8")
        missing = [name for name in markers if name not in content]
        assert not missing, f"{path.name} missing MCP profiles: {missing}"
