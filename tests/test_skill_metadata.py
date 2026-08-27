"""Validate the distributable zhihu-search Skill metadata and references."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "zhihu-search"
SKILL_MD = SKILL_DIR / "SKILL.md"
TRIGGER_EVALS = ROOT / "evals" / "trigger-evals.json"


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


def test_skill_frontmatter_has_specific_triggers_and_negative_boundaries() -> None:
    metadata = _frontmatter(SKILL_MD)
    assert set(metadata) == {"name", "description"}
    assert metadata["name"] == "zhihu-search"
    description = metadata["description"]
    assert isinstance(description, str)

    assert len(description) <= 700
    opening = description[:480]

    for cue in (
        "Chinese-community research",
        "Zhihu links",
        "real user experiences",
        "product reputation or pitfalls",
        "domestic hot topics",
        "知乎/知乎链接",
        "真实体验",
        "口碑",
        "避坑",
        "大家怎么看",
        "国内用户观点",
        "中文社区",
        "国内热点",
        "查中文来源",
    ):
        assert cue in opening

    assert "one narrow on-demand CLI query" in description
    assert "only when visible" in description
    assert "any general-knowledge request" not in description
    assert "even when the model already knows an answer" not in description
    assert "require an explicit request" in description

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


def test_trigger_eval_set_covers_positive_and_near_miss_cases() -> None:
    evals = json.loads(TRIGGER_EVALS.read_text(encoding="utf-8"))
    assert len(evals) == 12
    assert sum(item["should_trigger"] is True for item in evals) == 6
    assert sum(item["should_trigger"] is False for item in evals) == 6
    assert all(set(item) == {"query", "should_trigger"} for item in evals)
    assert all(len(item["query"]) >= 20 for item in evals)
    negative_queries = "\n".join(
        item["query"] for item in evals if item["should_trigger"] is False
    )
    for near_miss in ("官方中文文档", "Reddit", "贴出的这篇知乎回答"):
        assert near_miss in negative_queries


def test_setup_docs_share_the_high_frequency_mcp_anchor() -> None:
    setup_dir = ROOT / "setup"
    setup_readme = (setup_dir / "README.md").read_text(encoding="utf-8")
    assert "## 2. MCP（高频集成）" in setup_readme

    anchor = "(README.md#2-mcp高频集成)"
    for name in ("claude-code.md", "codex.md", "hanako-agent.md", "opencode.md"):
        assert anchor in (setup_dir / name).read_text(encoding="utf-8")


def test_openai_interface_matches_skill_behavior() -> None:
    metadata = yaml.safe_load(
        (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
    )
    assert metadata["interface"]["display_name"] == "Zhihu Search"
    short_description = metadata["interface"]["short_description"]
    assert 25 <= len(short_description) <= 64
    default_prompt = metadata["interface"]["default_prompt"]
    assert "$zhihu-search" in default_prompt
    assert "matching visible Zhihu MCP tool" in default_prompt
    assert "CLI on demand" in default_prompt
    assert metadata["policy"]["allow_implicit_invocation"] is True


def test_setup_reference_has_safe_codex_mcp_verification() -> None:
    setup = (SKILL_DIR / "references" / "setup.md").read_text(
        encoding="utf-8"
    )

    normalized = " ".join(setup.split())
    assert "Do not register a global stdio MCP server" in normalized
    assert "Skill discovery is independent of MCP registration" in normalized
    assert "exactly one matching core route" in normalized
    assert "persistent MCP only when the user explicitly asks" in normalized
    assert "must not print a secret fragment" in normalized
    assert "performs one real `hot_list(limit=1)` request" in normalized


def test_setup_reference_has_native_dsh_bundle_installation() -> None:
    setup = (SKILL_DIR / "references" / "setup.md").read_text(
        encoding="utf-8"
    )

    assert (
        'dsh plugin --profile web add '
        '"github:klarkxy/zhihu-search"'
        in setup
    )
    assert "dsh --profile web --dump-config" in setup
    assert "@deepseek-ai/dsh-skill-filesystem" in setup
    assert "zhihu-search-skill" in setup
    assert "must not start a persistent MCP server" in setup
    assert "never\nadd an Access Secret" in setup
