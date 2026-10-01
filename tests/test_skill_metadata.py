"""Offline checks for distributable Skill docs and evaluation fixtures, not LLM behavior."""

from __future__ import annotations

import json
import re
import shlex
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
            relative = Path(target.split("#", 1)[0])
            assert not relative.is_absolute(), f"absolute Skill reference: {target}"
            assert ".." not in relative.parts, f"reference escapes Skill: {target}"
            assert (markdown.parent / relative).is_file(), f"missing reference: {target}"


def test_skill_frontmatter_has_specific_triggers_and_negative_boundaries() -> None:
    metadata = _frontmatter(SKILL_MD)
    assert set(metadata) == {"name", "description"}
    assert metadata["name"] == SKILL_DIR.name
    description = metadata["description"]
    assert isinstance(description, str)
    assert 1 <= len(description) <= 1024
    for cue in ("知乎", "真实体验", "口碑", "避坑", "中文社区", "国内热点", "查中文来源"):
        assert cue in description
    for capability in ("question", "quota", "creator", "knowledge", "PDF/PPT", "setup"):
        assert capability in description
    for boundary in (
        "repository-local code questions", "pure math or logic", "translation",
        "user-provided content", "source restrictions", "require an explicit request",
    ):
        assert boundary in description


def test_skill_is_self_contained_after_install_copy(tmp_path: Path) -> None:
    installed = tmp_path / "zhihu-search"
    shutil.copytree(SKILL_DIR, installed)
    _assert_local_links_resolve(installed)
    for name in ("setup.md", "tools.md"):
        assert (installed / "references" / name).is_file()
        assert f"(references/{name})" in (installed / "SKILL.md").read_text(encoding="utf-8")


def test_main_skill_keeps_specialized_detail_in_references() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert len(text.splitlines()) < 180
    assert "## Official quota" not in text
    tools = (SKILL_DIR / "references" / "tools.md").read_text(encoding="utf-8")
    for command in (
        "quota", "user-contents", "user-followees", "user-collections", "user-favlists",
        "favlist-contents", "question-recommendations", "question-answers",
        "user-content-detail", "user-content-comments", "creator-account-stats",
        "creator-content-stats", "knowledge-bases", "knowledge-items", "knowledge-search",
        "knowledge-upload", "pdf-upload", "pdf-create", "pdf-status", "ppt-create",
        "ppt-status", "oauth-url", "oauth-token",
    ):
        assert f"uvx zhihu-search {command} " in tools or f"uvx zhihu-search {command}\n" in tools


def test_distributed_instructions_do_not_reintroduce_single_query_cap() -> None:
    paths = list(SKILL_DIR.rglob("*.md")) + list(SKILL_DIR.rglob("*.yaml"))
    for path in paths:
        normalized = " ".join(path.read_text(encoding="utf-8").split())
        for stale_rule in (
            "exactly one narrow command", "exactly one matching core route",
            "one narrow on-demand CLI query", "run `ask` instead of answering",
        ):
            assert stale_rule not in normalized, f"stale routing rule in {path}: {stale_rule}"


def test_trigger_eval_set_covers_positive_and_near_miss_cases() -> None:
    evals = json.loads(TRIGGER_EVALS.read_text(encoding="utf-8"))
    assert sum(item["should_trigger"] is True for item in evals) >= 6
    assert sum(item["should_trigger"] is False for item in evals) >= 6
    assert all(set(item) == {"query", "should_trigger"} for item in evals)
    assert all(isinstance(item["should_trigger"], bool) for item in evals)
    queries = [item["query"] for item in evals]
    assert all(isinstance(query, str) and len(query) >= 20 for query in queries)
    assert len(queries) == len(set(queries))
    negative_queries = "\n".join(item["query"] for item in evals if not item["should_trigger"])
    for near_miss in ("官方中文文档", "Reddit", "贴出的这篇知乎回答"):
        assert near_miss in negative_queries


def test_shell_examples_are_well_formed_and_never_start_a_bare_server() -> None:
    checked = 0
    for path in SKILL_DIR.rglob("*.md"):
        for block in re.findall(r"```bash\n(.*?)\n```", path.read_text(encoding="utf-8"), re.DOTALL):
            for line in block.splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                argv = shlex.split(line)
                if argv[:2] != ["uvx", "zhihu-search"]:
                    continue
                checked += 1
                assert len(argv) > 2, f"bare MCP startup example in {path}"
                assert argv[2] not in {"serve", "openwebui"}
                assert "--oauth-token" not in argv and "--app-key" not in argv
                if argv[2] == "search":
                    assert 2 <= len(argv[3]) <= 100
                    assert "--page" not in argv and "--offset" not in argv
                    count = int(argv[argv.index("--count") + 1]) if "--count" in argv else 10
                    scope = argv[argv.index("--scope") + 1] if "--scope" in argv else "zhihu"
                    assert scope in {"zhihu", "web"}
                    assert 1 <= count <= (10 if scope == "zhihu" else 20)
    assert checked >= 25


def test_setup_docs_share_the_high_frequency_mcp_anchor() -> None:
    setup_dir = ROOT / "setup"
    setup_readme = (setup_dir / "README.md").read_text(encoding="utf-8")
    assert "## 2. MCP（高频集成）" in setup_readme
    anchor = "(README.md#2-mcp高频集成)"
    for name in ("claude-code.md", "codex.md", "hanako-agent.md", "opencode.md"):
        assert anchor in (setup_dir / name).read_text(encoding="utf-8")


def test_openai_interface_matches_skill_behavior() -> None:
    metadata = yaml.safe_load((SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    assert metadata["interface"]["display_name"] == "Zhihu Search"
    assert 25 <= len(metadata["interface"]["short_description"]) <= 64
    prompt = metadata["interface"]["default_prompt"]
    for cue in ("$zhihu-search", "matching visible Zhihu MCP tool", "CLI on demand"):
        assert cue in prompt
    assert metadata["policy"]["allow_implicit_invocation"] is True


def test_setup_reference_has_safe_codex_mcp_verification() -> None:
    setup = (SKILL_DIR / "references" / "setup.md").read_text(encoding="utf-8")
    normalized = " ".join(setup.split())
    for cue in (
        "Do not register a global stdio MCP server", "Skill discovery is independent of MCP registration",
        "persistent MCP only when the user explicitly asks",
        "must not print a secret fragment", "performs one real `hot_list(limit=1)` request",
    ):
        assert cue in normalized


def test_setup_reference_points_dsh_users_to_dsh_plugins() -> None:
    setup = (SKILL_DIR / "references" / "setup.md").read_text(encoding="utf-8")
    assert "dsh plugin --profile web add @klarkxy/dsh-zhihu" in setup
    assert "https://github.com/klarkxy/dsh-plugins/tree/main/plugins/dsh-zhihu" in setup
    assert "dsh plugin --profile web remove dsh-plugin-zhihu-search" in setup
    assert 'add "github:klarkxy/zhihu-search"' not in setup
    assert "ZHIHU_ACCESS_TOKEN" in setup
    assert "Never add it to a profile" in setup


def test_eval_docs_distinguish_structural_checks_from_model_evaluation() -> None:
    text = (ROOT / "evals" / "README.md").read_text(encoding="utf-8")
    assert "do **not** run a model" in text
    assert "mocked tool results" in text
    assert "unexecuted fixtures" in text
