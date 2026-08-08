"""Validate the distributable zhihu-search Skill metadata and references."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "zhihu-search"
SKILL_MD = SKILL_DIR / "SKILL.md"


def _frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    assert match is not None, "SKILL.md must start with YAML frontmatter"
    parsed = yaml.safe_load(match.group(1))
    assert isinstance(parsed, dict)
    return parsed


def _assert_local_links_resolve(skill_dir: Path) -> None:
    for markdown in skill_dir.rglob("*.md"):
        text = markdown.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if "://" in target or target.startswith("#"):
                continue
            clean_target = target.split("#", 1)[0]
            relative = Path(clean_target)
            assert ".." not in relative.parts, f"reference escapes Skill: {target}"
            assert (markdown.parent / relative).exists(), f"missing reference: {target}"


def test_skill_frontmatter_has_broad_triggers_and_negative_boundaries() -> None:
    metadata = _frontmatter(SKILL_MD)
    assert set(metadata) == {"name", "description"}
    assert metadata["name"] == "zhihu-search"
    description = metadata["description"]
    assert isinstance(description, str)

    for cue in (
        "查资料",
        "核实信息",
        "找来源",
        "真实经验",
        "口碑",
        "大家怎么看",
        "解释或分析",
        "为什么/是什么",
        "最近热点",
        "安装、配置或排障",
    ):
        assert cue in description

    assert "even when the model already knows an answer" in description
    assert "authorized Zhihu user data" in description
    assert "Zhihu-backed PDF/PPT tasks" in description
    assert "Zhihu OAuth flows" in description

    for boundary in (
        "repository-local code questions",
        "pure math or logic",
        "translation",
        "user-provided content",
    ):
        assert boundary in description


def test_skill_is_self_contained_after_install_copy(tmp_path: Path) -> None:
    installed = tmp_path / "zhihu-search"
    shutil.copytree(SKILL_DIR, installed)
    _assert_local_links_resolve(installed)
    assert (installed / "references" / "setup.md").is_file()


def test_openai_interface_matches_skill_behavior() -> None:
    metadata = yaml.safe_load(
        (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
    )
    assert metadata["interface"]["display_name"] == "Zhihu Search"
    short_description = metadata["interface"]["short_description"]
    assert 25 <= len(short_description) <= 64
    default_prompt = metadata["interface"]["default_prompt"]
    assert "$zhihu-search" in default_prompt
    assert "MCP" in default_prompt
    assert metadata["policy"]["allow_implicit_invocation"] is True
