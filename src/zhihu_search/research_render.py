"""Validate a host-written research report and render local files.

The renderer does not search, does not call a model, and does not publish.
It checks that citations exist in the evidence packet, that interactive
numbers are either present in a cited excerpt or labeled as assumptions, and
that uncertain dates stay out of the confirmed timeline. HTML is a single
self-contained file: no remote assets, no source-controlled scripts, and no
``eval``.

This is an independent implementation of the report-plus-interactive-page
shape described in Zhihu's public data-platform material. Official skill
prose, renderers, CSS and JavaScript are not copied.
"""

from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path
from typing import Any

from .research import SCHEMA as EVIDENCE_SCHEMA


REPORT_SCHEMA = "zhihu-search.report.v1"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_EVIDENCE_ID = re.compile(r"^e[1-9][0-9]{0,3}$")
_POPULATION = ("全体用户", "所有知乎用户", "所有用户都", "知乎用户都认为")
_COMMON_KEYS = {
    "schema",
    "workflow",
    "title",
    "question",
    "status",
    "incomplete_reason",
    "summary",
    "assumptions",
    "conclusions",
    "conflicts",
}
_WORKFLOW_KEYS = {
    "deep": _COMMON_KEYS | {
        "scenarios",
        "comparisons",
        "disputes",
        "mechanisms",
        "interactive",
    },
    "observe": _COMMON_KEYS | {"viewpoints", "open_questions", "progress"},
    "recent": _COMMON_KEYS | {"window_days", "changes", "timeline", "next_checks"},
}
SOURCE_NOTE = (
    "工作流对应知乎数据开放平台公开介绍的深度研究、知乎观察和近况速览。"
    "检索使用已经接入的开放平台接口，说明见 "
    "https://developer.zhihu.com/docs?key=zhihu_cli 。"
    "本页由 zhihu-search 独立生成，没有复制官方 Skill、脚本或样式，也不会发布到知乎。"
)

INTERPRETER_JS = """
function evalAst(node, env) {
  if (Object.prototype.hasOwnProperty.call(node, "ref")) return env[node.ref];
  var args = [];
  for (var i = 0; i < node.args.length; i++) args.push(evalAst(node.args[i], env));
  if (node.op === "add") return args[0] + args[1];
  if (node.op === "sub") return args[0] - args[1];
  if (node.op === "mul") return args[0] * args[1];
  if (node.op === "div") return args[1] === 0 ? NaN : args[0] / args[1];
  if (node.op === "neg") return -args[0];
  return NaN;
}
function formatNum(value) {
  if (typeof value !== "number" || !isFinite(value)) return "无法计算";
  var text = value.toFixed(6).replace(/0+$/, "").replace(/\\.$/, "");
  return text === "" ? "0" : text;
}
""".strip()


class ReportRejected(Exception):
    """The synthesis is not safe to present as a research report."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("报告未渲染：\n" + "\n".join(f"- {item}" for item in errors))


class _Check:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def add(self, message: str) -> None:
        if message not in self.errors:
            self.errors.append(message)

    def finish(self) -> None:
        if self.errors:
            raise ReportRejected(self.errors)


def render_report(evidence: Any, report: Any) -> dict[str, Any]:
    """Return markdown, html and normalized data, or reject the synthesis."""
    check = _Check()
    packet = _packet(evidence, check)
    body = _report(report, packet, check)
    check.finish()
    data = _normalized(packet, body)
    markdown = _markdown(data)
    page = _html(data)
    return {"markdown": markdown, "html": page, "data": data}


def write_report(evidence: Any, report: Any, out_dir: str | Path) -> dict[str, Any]:
    """Render and write report.md, report.json and report.html."""
    rendered = render_report(evidence, report)
    target = Path(out_dir)
    if target.exists() and not target.is_dir():
        raise ReportRejected(["输出路径已存在并且不是目录。"])
    target.mkdir(parents=True, exist_ok=True)
    (target / "report.md").write_text(rendered["markdown"], encoding="utf-8")
    (target / "report.json").write_text(
        json.dumps(rendered["data"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (target / "report.html").write_text(rendered["html"], encoding="utf-8")
    rendered["directory"] = str(target)
    rendered["files"] = ["report.md", "report.json", "report.html"]
    return rendered


def format_number(value: float) -> str:
    """Match the page script's six-digit rounding for finite results."""
    if not math.isfinite(value):
        return "无法计算"
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _packet(value: Any, check: _Check) -> dict[str, Any]:
    if not isinstance(value, dict):
        check.add("证据包必须是对象。")
        check.finish()
    if value.get("schema") != EVIDENCE_SCHEMA or value.get("role") != "evidence":
        check.add("证据包 schema 或 role 不正确。不能把别的 JSON 渲染成研究报告。")
    if value.get("finished_research") is not False:
        check.add("证据包 finished_research 必须为 false。检索结果本身不是研究报告。")
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        check.add("证据包没有证据。空检索不能渲染成研究报告。")
        check.finish()
    ids: list[str] = []
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            check.add("证据项缺少 id。")
            continue
        if not _EVIDENCE_ID.fullmatch(item["id"]):
            check.add(f"证据 id 不合法：{item['id']}")
        if item["id"] in ids:
            check.add(f"证据 id 重复：{item['id']}")
        ids.append(item["id"])
    if value.get("workflow") not in _WORKFLOW_KEYS:
        check.add("证据包 workflow 不正确。")
    if not isinstance(value.get("question"), str) or not value.get("question"):
        check.add("证据包缺少 question。")
    check.finish()
    return value


def _report(value: Any, packet: dict[str, Any], check: _Check) -> dict[str, Any]:
    if not isinstance(value, dict):
        check.add("综合结果必须是对象。只提交证据包不会生成报告。")
        check.finish()
    workflow = packet["workflow"]
    allowed = _WORKFLOW_KEYS[workflow]
    extra = sorted(set(value) - allowed)
    missing = sorted(allowed - set(value))
    if value.get("schema") != REPORT_SCHEMA:
        check.add("综合结果 schema 必须是 zhihu-search.report.v1。")
    if extra:
        check.add("综合结果含有未定义字段：" + "、".join(extra))
    if missing:
        check.add("综合结果缺少字段：" + "、".join(missing))
    if value.get("workflow") != workflow:
        check.add("综合结果的 workflow 必须与证据包一致。")
    if value.get("question") != packet.get("question"):
        check.add("综合结果的 question 必须与证据包一致，不能换题渲染。")
    status = value.get("status")
    if status not in {"complete", "partial"}:
        check.add("status 必须是 complete 或 partial。")
    reason = _text(value.get("incomplete_reason"), "incomplete_reason", check, required=False, limit=500)
    if status == "complete":
        if packet.get("status") != "complete":
            check.add("证据包不完整时，报告 status 不能是 complete。")
        if reason:
            check.add("complete 报告的 incomplete_reason 必须为空。")
    elif status == "partial" and not reason:
        check.add("partial 报告必须写 incomplete_reason。")
    title = _text(value.get("title"), "title", check, limit=200)
    summary = _text(value.get("summary"), "summary", check, limit=4000)
    assumptions = _assumptions(value.get("assumptions"), check)
    known = {item["id"]: item for item in packet["evidence"]}
    assumption_ids = {item["id"] for item in assumptions}
    conclusions = _blocks(
        value.get("conclusions"),
        "conclusions",
        check,
        known,
        assumption_ids,
        extra=("condition",),
    )
    conflicts = _conflicts(value.get("conflicts"), check, known)
    cited: set[str] = set()
    for block in conclusions:
        cited.update(block["evidence_ids"])
    for block in conflicts:
        cited.update(block["evidence_ids"])

    specific: dict[str, Any] = {}
    if workflow == "deep":
        specific = _deep(value, check, known, assumption_ids, cited)
    elif workflow == "observe":
        specific = _observe(value, check, known, cited)
    else:
        specific = _recent(value, packet, check, known, assumption_ids, cited)

    if status == "complete" and cited != set(known):
        missed = sorted(set(known) - cited)
        check.add("complete 报告必须引用全部证据，未引用：" + "、".join(missed))
    if not cited:
        check.add("报告没有引用任何证据。")
    check.finish()
    return {
        "title": title,
        "question": packet["question"],
        "workflow": workflow,
        "status": status,
        "incomplete_reason": reason,
        "summary": summary,
        "assumptions": assumptions,
        "conclusions": conclusions,
        "conflicts": conflicts,
        **specific,
    }


def _deep(
    value: dict[str, Any],
    check: _Check,
    known: dict[str, dict[str, Any]],
    assumption_ids: set[str],
    cited: set[str],
) -> dict[str, Any]:
    scenarios = _string_list(value.get("scenarios"), "scenarios", check, limit=8)
    comparisons = _comparisons(value.get("comparisons"), check, known, cited)
    disputes = _disputes(value.get("disputes"), check, known, cited)
    mechanisms = _simple_list(value.get("mechanisms"), "mechanisms", check, known, cited)
    interactive = _interactive(
        value.get("interactive"),
        check,
        known,
        assumption_ids,
    )
    if interactive:
        for item in interactive["inputs"]:
            if item.get("evidence_id"):
                cited.add(item["evidence_id"])
    if value.get("status") == "complete" and not scenarios:
        check.add("深度研究的 complete 报告至少要写一个适用场景。")
    if value.get("status") == "complete" and not value.get("conclusions"):
        check.add("深度研究的 complete 报告至少要有一条带条件的结论。")
    for item in mechanisms:
        cited.update(item["evidence_ids"])
    return {
        "scenarios": scenarios,
        "comparisons": comparisons,
        "disputes": disputes,
        "mechanisms": mechanisms,
        "interactive": interactive,
    }


def _observe(
    value: dict[str, Any],
    check: _Check,
    known: dict[str, dict[str, Any]],
    cited: set[str],
) -> dict[str, Any]:
    viewpoints = _simple_list(value.get("viewpoints"), "viewpoints", check, known, cited)
    progress = _simple_list(value.get("progress"), "progress", check, known, cited)
    questions = _simple_list(
        value.get("open_questions"),
        "open_questions",
        check,
        known,
        cited,
        allow_empty_evidence=True,
    )
    if value.get("status") == "complete" and not viewpoints:
        check.add("知乎观察的 complete 报告至少要有一条观点，并引用证据。")
    if value.get("status") == "complete" and not progress:
        check.add("知乎观察的 complete 报告至少要有一条进展，并引用证据。")
    return {
        "viewpoints": viewpoints,
        "progress": progress,
        "open_questions": questions,
        "single_viewpoint": len(viewpoints) < 2,
    }


def _recent(
    value: dict[str, Any],
    packet: dict[str, Any],
    check: _Check,
    known: dict[str, dict[str, Any]],
    assumption_ids: set[str],
    cited: set[str],
) -> dict[str, Any]:
    window = value.get("window_days")
    expected = packet.get("dates", {}).get("window_days")
    if window != expected:
        check.add(f"window_days 必须与证据包一致（{expected}）。")
    changes = _changes(value.get("changes"), check, known, cited)
    checks = _string_list(value.get("next_checks"), "next_checks", check, limit=8)
    events = _events(value.get("timeline"), check, known, assumption_ids, cited)
    if value.get("status") == "complete" and not changes:
        check.add("近况速览的 complete 报告至少要有一条变化或影响。")
    if value.get("status") == "complete" and not checks:
        check.add("近况速览的 complete 报告至少要有一条后续核对。")
    confirmed, uncertain = _merge_events(events, check)
    return {
        "window_days": window,
        "changes": changes,
        "next_checks": checks,
        "confirmed_timeline": confirmed,
        "uncertain_dates": uncertain,
    }


def _assumptions(value: Any, check: _Check) -> list[dict[str, str]]:
    items = _list(value, "assumptions", check, limit=20)
    result = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        path = f"assumptions[{index}]"
        if not isinstance(item, dict) or set(item) != {"id", "text"}:
            check.add(f"{path} 只能包含 id 和 text。")
            continue
        ident = item["id"]
        if not isinstance(ident, str) or not _IDENT.fullmatch(ident) or not ident.startswith("a"):
            check.add(f"{path}.id 必须以 a 开头，并且只含小写字母、数字和下划线。")
            ident = ""
        if ident in seen:
            check.add(f"假设 id 重复：{ident}")
        seen.add(ident)
        text = _text(item.get("text"), f"{path}.text", check, limit=1000)
        result.append({"id": ident, "text": text})
    return result


def _blocks(
    value: Any,
    name: str,
    check: _Check,
    known: dict[str, dict[str, Any]],
    assumption_ids: set[str],
    *,
    extra: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    items = _list(value, name, check, limit=12)
    result = []
    keys = {"id", "text", "evidence_ids", "assumption_ids", *extra}
    for index, item in enumerate(items):
        path = f"{name}[{index}]"
        if not isinstance(item, dict) or set(item) != keys:
            check.add(f"{path} 字段必须正好是 {sorted(keys)}。")
            continue
        ident = _ident(item.get("id"), f"{path}.id", check)
        text = _text(item.get("text"), f"{path}.text", check, limit=2000)
        evidence_ids = _evidence_ids(item.get("evidence_ids"), f"{path}.evidence_ids", check, known, allow_empty=True)
        assumptions = _id_list(item.get("assumption_ids"), f"{path}.assumption_ids", check, assumption_ids)
        if not evidence_ids and not assumptions:
            check.add(f"{path} 必须引用证据或假设。")
        block: dict[str, Any] = {
            "id": ident,
            "text": text,
            "evidence_ids": evidence_ids,
            "assumption_ids": assumptions,
        }
        for key in extra:
            block[key] = _text(item.get(key), f"{path}.{key}", check, limit=500)
        result.append(block)
    return result


def _simple_list(
    value: Any,
    name: str,
    check: _Check,
    known: dict[str, dict[str, Any]],
    cited: set[str],
    *,
    allow_empty_evidence: bool = False,
) -> list[dict[str, Any]]:
    items = _list(value, name, check, limit=12)
    result = []
    for index, item in enumerate(items):
        path = f"{name}[{index}]"
        if not isinstance(item, dict) or set(item) != {"id", "text", "evidence_ids"}:
            check.add(f"{path} 只能包含 id、text、evidence_ids。")
            continue
        evidence_ids = _evidence_ids(
            item.get("evidence_ids"),
            f"{path}.evidence_ids",
            check,
            known,
            allow_empty=allow_empty_evidence,
        )
        cited.update(evidence_ids)
        result.append(
            {
                "id": _ident(item.get("id"), f"{path}.id", check),
                "text": _text(item.get("text"), f"{path}.text", check, limit=2000),
                "evidence_ids": evidence_ids,
            }
        )
    return result


def _comparisons(
    value: Any,
    check: _Check,
    known: dict[str, dict[str, Any]],
    cited: set[str],
) -> list[dict[str, Any]]:
    items = _list(value, "comparisons", check, limit=8)
    result = []
    for index, item in enumerate(items):
        path = f"comparisons[{index}]"
        if not isinstance(item, dict) or set(item) != {"id", "topic", "spec", "experience"}:
            check.add(f"{path} 只能包含 id、topic、spec、experience。")
            continue
        result.append(
            {
                "id": _ident(item.get("id"), f"{path}.id", check),
                "topic": _text(item.get("topic"), f"{path}.topic", check, limit=200),
                "spec": _side(item.get("spec"), f"{path}.spec", check, known, cited),
                "experience": _side(item.get("experience"), f"{path}.experience", check, known, cited),
            }
        )
    return result


def _side(
    value: Any,
    path: str,
    check: _Check,
    known: dict[str, dict[str, Any]],
    cited: set[str],
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"text", "evidence_ids"}:
        check.add(f"{path} 只能包含 text 和 evidence_ids。")
        return {"text": "", "evidence_ids": []}
    evidence_ids = _evidence_ids(value.get("evidence_ids"), f"{path}.evidence_ids", check, known)
    cited.update(evidence_ids)
    return {
        "text": _text(value.get("text"), f"{path}.text", check, limit=2000),
        "evidence_ids": evidence_ids,
    }


def _disputes(
    value: Any,
    check: _Check,
    known: dict[str, dict[str, Any]],
    cited: set[str],
) -> list[dict[str, Any]]:
    items = _list(value, "disputes", check, limit=8)
    result = []
    for index, item in enumerate(items):
        path = f"disputes[{index}]"
        if not isinstance(item, dict) or set(item) != {"id", "topic", "positions"}:
            check.add(f"{path} 只能包含 id、topic、positions。")
            continue
        positions = item.get("positions")
        if not isinstance(positions, list) or len(positions) < 2:
            check.add(f"{path}.positions 至少要有两个并列说法。")
            positions = []
        rendered = []
        for offset, position in enumerate(positions):
            rendered.append(_side(position, f"{path}.positions[{offset}]", check, known, cited))
        result.append(
            {
                "id": _ident(item.get("id"), f"{path}.id", check),
                "topic": _text(item.get("topic"), f"{path}.topic", check, limit=200),
                "positions": rendered,
            }
        )
    return result


def _conflicts(
    value: Any,
    check: _Check,
    known: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    items = _list(value, "conflicts", check, limit=8)
    result = []
    for index, item in enumerate(items):
        path = f"conflicts[{index}]"
        if not isinstance(item, dict) or set(item) != {"id", "topic", "note", "evidence_ids"}:
            check.add(f"{path} 只能包含 id、topic、note、evidence_ids。")
            continue
        evidence_ids = _evidence_ids(item.get("evidence_ids"), f"{path}.evidence_ids", check, known)
        if len(evidence_ids) < 2:
            check.add(f"{path} 至少要引用两条相互冲突的证据。")
        result.append(
            {
                "id": _ident(item.get("id"), f"{path}.id", check),
                "topic": _text(item.get("topic"), f"{path}.topic", check, limit=200),
                "note": _text(item.get("note"), f"{path}.note", check, limit=1000),
                "evidence_ids": evidence_ids,
            }
        )
    return result


def _changes(
    value: Any,
    check: _Check,
    known: dict[str, dict[str, Any]],
    cited: set[str],
) -> list[dict[str, Any]]:
    items = _list(value, "changes", check, limit=12)
    result = []
    for index, item in enumerate(items):
        path = f"changes[{index}]"
        if not isinstance(item, dict) or set(item) != {"id", "text", "kind", "evidence_ids"}:
            check.add(f"{path} 只能包含 id、text、kind、evidence_ids。")
            continue
        if item.get("kind") not in {"new", "impact"}:
            check.add(f"{path}.kind 必须是 new 或 impact。")
        evidence_ids = _evidence_ids(item.get("evidence_ids"), f"{path}.evidence_ids", check, known)
        cited.update(evidence_ids)
        result.append(
            {
                "id": _ident(item.get("id"), f"{path}.id", check),
                "text": _text(item.get("text"), f"{path}.text", check, limit=2000),
                "kind": item.get("kind"),
                "evidence_ids": evidence_ids,
            }
        )
    return result


def _events(
    value: Any,
    check: _Check,
    known: dict[str, dict[str, Any]],
    assumption_ids: set[str],
    cited: set[str],
) -> list[dict[str, Any]]:
    items = _list(value, "timeline", check, limit=30)
    keys = {
        "id",
        "title",
        "uncertain",
        "event_date",
        "event_date_basis",
        "assumption_id",
        "evidence_ids",
        "impact",
        "merge_key",
    }
    result = []
    for index, item in enumerate(items):
        path = f"timeline[{index}]"
        if not isinstance(item, dict) or set(item) != keys:
            check.add(f"{path} 字段不完整或含有未定义字段。")
            continue
        evidence_ids = _evidence_ids(item.get("evidence_ids"), f"{path}.evidence_ids", check, known)
        cited.update(evidence_ids)
        uncertain = item.get("uncertain")
        if type(uncertain) is not bool:
            check.add(f"{path}.uncertain 必须是布尔值。")
            uncertain = True
        event_date = item.get("event_date")
        basis = item.get("event_date_basis")
        assumption_id = item.get("assumption_id")
        merge_key = item.get("merge_key")
        if merge_key is not None and (not isinstance(merge_key, str) or not _IDENT.fullmatch(merge_key)):
            check.add(f"{path}.merge_key 不合法。")
            merge_key = None
        if uncertain:
            if event_date is not None or basis is not None or assumption_id is not None:
                check.add(f"{path} 日期不确定时，事件日期、依据和假设都必须为空。")
        else:
            if not isinstance(event_date, str) or not _DATE.fullmatch(event_date):
                check.add(f"{path}.event_date 必须是 YYYY-MM-DD。")
                event_date = None
            if basis not in {"excerpt", "assumption"}:
                check.add(f"{path}.event_date_basis 必须是 excerpt 或 assumption。")
            if basis == "excerpt":
                if assumption_id is not None:
                    check.add(f"{path} 用正文作为日期依据时不能再挂假设。")
                if isinstance(event_date, str) and not any(
                    event_date in _haystack(known[item_id]) for item_id in evidence_ids if item_id in known
                ):
                    check.add(f"{path} 的事件日期没有出现在所引证据的标题或摘录中。")
            elif basis == "assumption":
                if assumption_id not in assumption_ids:
                    check.add(f"{path}.assumption_id 没有对应假设。")
        result.append(
            {
                "id": _ident(item.get("id"), f"{path}.id", check),
                "title": _text(item.get("title"), f"{path}.title", check, limit=200),
                "uncertain": uncertain,
                "event_date": event_date if not uncertain else None,
                "event_date_basis": basis if not uncertain else None,
                "assumption_id": assumption_id if not uncertain else None,
                "evidence_ids": evidence_ids,
                "impact": _text(item.get("impact"), f"{path}.impact", check, limit=1000),
                "merge_key": merge_key,
            }
        )
    return result


def _merge_events(
    events: list[dict[str, Any]],
    check: _Check,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in events:
        key = event["merge_key"] or event["id"]
        current = groups.get(key)
        if current is None:
            groups[key] = {
                **event,
                "evidence_ids": list(event["evidence_ids"]),
            }
            order.append(key)
            continue
        if (
            current["uncertain"] != event["uncertain"]
            or current["event_date"] != event["event_date"]
            or current["event_date_basis"] != event["event_date_basis"]
        ):
            check.add(f"同一 merge_key {key} 的事件日期不一致，不能合并成确认事件。")
            continue
        for evidence_id in event["evidence_ids"]:
            if evidence_id not in current["evidence_ids"]:
                current["evidence_ids"].append(evidence_id)
    confirmed = [groups[key] for key in order if not groups[key]["uncertain"]]
    uncertain = [groups[key] for key in order if groups[key]["uncertain"]]
    confirmed.sort(key=lambda item: (item["event_date"] or "", item["id"]))
    return confirmed, uncertain


def _interactive(
    value: Any,
    check: _Check,
    known: dict[str, dict[str, Any]],
    assumption_ids: set[str],
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"title", "inputs", "formulas"}:
        check.add("interactive 必须是 null，或只含 title、inputs、formulas。")
        return None
    title = _text(value.get("title"), "interactive.title", check, limit=200)
    inputs = _list(value.get("inputs"), "interactive.inputs", check, limit=8)
    formulas = _list(value.get("formulas"), "interactive.formulas", check, limit=8)
    if not inputs or not formulas:
        check.add("交互块一旦出现，就要有输入和公式。没有来源的数字不能留空占位。")
    parsed_inputs = []
    input_ids: set[str] = set()
    env: dict[str, float] = {}
    input_keys = {
        "id",
        "label",
        "value",
        "min",
        "max",
        "step",
        "unit",
        "evidence_id",
        "value_assumption_id",
        "bounds_assumption_id",
    }
    for index, item in enumerate(inputs):
        path = f"interactive.inputs[{index}]"
        if not isinstance(item, dict) or set(item) != input_keys:
            check.add(f"{path} 字段不完整或含有未定义字段。")
            continue
        ident = _ident(item.get("id"), f"{path}.id", check)
        if ident in input_ids:
            check.add(f"交互输入 id 重复：{ident}")
        input_ids.add(ident)
        number = _number(item.get("value"), f"{path}.value", check)
        low = _number(item.get("min"), f"{path}.min", check)
        high = _number(item.get("max"), f"{path}.max", check)
        step = _number(item.get("step"), f"{path}.step", check)
        if number is not None and low is not None and high is not None and step is not None:
            if not low <= number <= high or step <= 0 or high <= low:
                check.add(f"{path} 的范围、步长和当前值不成立。")
        evidence_id = item.get("evidence_id")
        assumption_id = item.get("value_assumption_id")
        bounds_id = item.get("bounds_assumption_id")
        if (evidence_id is None) == (assumption_id is None):
            check.add(f"{path} 的当前值必须正好有一个来源：证据或假设。")
        if evidence_id is not None:
            if evidence_id not in known:
                check.add(f"{path}.evidence_id 不在证据包中。")
            elif number is not None and not _number_in_text(number, _haystack(known[evidence_id])):
                check.add(f"{path}.value 没有出现在证据 {evidence_id} 的标题或摘录中。")
        if assumption_id is not None and assumption_id not in assumption_ids:
            check.add(f"{path}.value_assumption_id 没有对应假设。")
        if bounds_id not in assumption_ids:
            check.add(f"{path}.bounds_assumption_id 必须指向解释滑块范围的假设。")
        if number is not None:
            env[ident] = float(number)
        parsed_inputs.append(
            {
                "id": ident,
                "label": _text(item.get("label"), f"{path}.label", check, limit=200),
                "value": number,
                "min": low,
                "max": high,
                "step": step,
                "unit": _text(item.get("unit"), f"{path}.unit", check, limit=40),
                "evidence_id": evidence_id,
                "value_assumption_id": assumption_id,
                "bounds_assumption_id": bounds_id,
            }
        )
    parsed_formulas = []
    formula_keys = {"id", "label", "expression", "unit", "assumption_ids"}
    for index, item in enumerate(formulas):
        path = f"interactive.formulas[{index}]"
        if not isinstance(item, dict) or set(item) != formula_keys:
            check.add(f"{path} 字段不完整或含有未定义字段。")
            continue
        expression = item.get("expression")
        ast = None
        if not isinstance(expression, str):
            check.add(f"{path}.expression 必须是字符串。")
        else:
            try:
                ast = parse_formula(expression, input_ids)
            except FormulaError as exc:
                check.add(f"{path}.expression {exc}")
        assumptions = _id_list(item.get("assumption_ids"), f"{path}.assumption_ids", check, assumption_ids)
        if not assumptions:
            check.add(f"{path} 必须用假设说明这个计算公式，不能把公式伪装成上游事实。")
        result = None
        if ast is not None and all(ident in env for ident in input_ids):
            try:
                result = evaluate(ast, env)
            except FormulaError as exc:
                check.add(f"{path} {exc}")
        parsed_formulas.append(
            {
                "id": _ident(item.get("id"), f"{path}.id", check),
                "label": _text(item.get("label"), f"{path}.label", check, limit=200),
                "expression": expression if isinstance(expression, str) else "",
                "unit": _text(item.get("unit"), f"{path}.unit", check, limit=40),
                "assumption_ids": assumptions,
                "ast": ast,
                "default_result": result,
            }
        )
    if any(item["default_result"] is None for item in parsed_formulas):
        return {
            "title": title,
            "inputs": parsed_inputs,
            "formulas": parsed_formulas,
        }
    return {"title": title, "inputs": parsed_inputs, "formulas": parsed_formulas}


class FormulaError(Exception):
    """A formula contains a literal, an unknown name, or an unsafe token."""


def parse_formula(expression: str, names: set[str]) -> dict[str, Any]:
    """Parse identifiers and + - * / only. Numeric literals are rejected."""
    if len(expression) > 200:
        raise FormulaError("超过 200 个字符。")
    tokens = _tokenize(expression)
    parser = _Parser(tokens, names)
    ast = parser.parse_expression()
    parser.end()
    return ast


def evaluate(ast: dict[str, Any], env: dict[str, float]) -> float:
    if "ref" in ast:
        if ast["ref"] not in env:
            raise FormulaError(f"缺少输入 {ast['ref']}。")
        return env[ast["ref"]]
    args = [evaluate(item, env) for item in ast["args"]]
    if ast["op"] == "neg":
        return -args[0]
    if ast["op"] == "add":
        value = args[0] + args[1]
    elif ast["op"] == "sub":
        value = args[0] - args[1]
    elif ast["op"] == "mul":
        value = args[0] * args[1]
    elif ast["op"] == "div":
        if args[1] == 0:
            raise FormulaError("默认输入使分母为 0。")
        value = args[0] / args[1]
    else:
        raise FormulaError("公式含有未定义运算。")
    if not math.isfinite(value):
        raise FormulaError("默认输入的计算结果不是有限数。")
    return value


def _tokenize(expression: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    index = 0
    while index < len(expression):
        char = expression[index]
        if char.isspace():
            index += 1
            continue
        if char.isdigit() or (char == "." and index + 1 < len(expression) and expression[index + 1].isdigit()):
            raise FormulaError("不能写数字字面量。每个数字都要做成带证据或假设的输入。")
        if char in "+-*/()":
            tokens.append((char, char))
            index += 1
            continue
        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", expression[index:])
        if not match:
            raise FormulaError(f"含有不能使用的字符 {char!r}。")
        tokens.append(("name", match.group(0)))
        index += len(match.group(0))
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], names: set[str]) -> None:
        self.tokens = tokens
        self.names = names
        self.index = 0

    def peek(self) -> tuple[str, str] | None:
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]

    def take(self, kind: str | None = None) -> tuple[str, str]:
        token = self.peek()
        if token is None or (kind is not None and token[0] != kind):
            raise FormulaError("公式不完整。")
        self.index += 1
        return token

    def parse_expression(self) -> dict[str, Any]:
        node = self.parse_term()
        while self.peek() and self.peek()[0] in {"+", "-"}:
            op = "add" if self.take()[0] == "+" else "sub"
            node = {"op": op, "args": [node, self.parse_term()]}
        return node

    def parse_term(self) -> dict[str, Any]:
        node = self.parse_factor()
        while self.peek() and self.peek()[0] in {"*", "/"}:
            op = "mul" if self.take()[0] == "*" else "div"
            node = {"op": op, "args": [node, self.parse_factor()]}
        return node

    def parse_factor(self) -> dict[str, Any]:
        token = self.peek()
        if token is None:
            raise FormulaError("公式不完整。")
        if token[0] == "-":
            self.take("-")
            return {"op": "neg", "args": [self.parse_factor()]}
        if token[0] == "(":
            self.take("(")
            node = self.parse_expression()
            self.take(")")
            return node
        if token[0] == "name":
            name = self.take("name")[1]
            if name not in self.names:
                raise FormulaError(f"未知输入 {name}。")
            return {"ref": name}
        raise FormulaError("公式含有不能使用的记号。")

    def end(self) -> None:
        if self.peek() is not None:
            raise FormulaError("公式在结束后还有多余内容。")


def _normalized(packet: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    known = {item["id"]: item for item in packet["evidence"]}
    cited_ids: list[str] = []
    for value in _walk_ids(body):
        if value not in cited_ids:
            cited_ids.append(value)
    finished = body["status"] == "complete"
    data = {
        "schema": REPORT_SCHEMA,
        "finished_research": finished,
        "publishable": False,
        "network_assets": False,
        "status": body["status"],
        "workflow": body["workflow"],
        "title": body["title"],
        "question": body["question"],
        "incomplete_reason": body["incomplete_reason"],
        "summary": body["summary"],
        "sample_note": packet["sample"]["note"],
        "source_note": SOURCE_NOTE,
        "assumptions": body["assumptions"],
        "conclusions": body["conclusions"],
        "conflicts": body["conflicts"],
        "sections": {
            key: value
            for key, value in body.items()
            if key
            not in {
                "title",
                "question",
                "workflow",
                "status",
                "incomplete_reason",
                "summary",
                "assumptions",
                "conclusions",
                "conflicts",
            }
        },
        "cited_evidence": [known[item_id] for item_id in cited_ids if item_id in known],
        "evidence_chronology": packet.get("chronology"),
        "evidence_dates": packet.get("dates"),
        "evidence_budget": packet.get("budget"),
        "evidence_limitations": packet.get("limitations"),
        "limitations": _render_limitations(packet, body),
    }
    interactive = body.get("interactive")
    if interactive:
        data["sections"]["interactive"] = {
            **interactive,
            "default_results": [
                {
                    "id": formula["id"],
                    "label": formula["label"],
                    "unit": formula["unit"],
                    "value": formula["default_result"],
                    "display": format_number(formula["default_result"])
                    if isinstance(formula["default_result"], float)
                    else None,
                }
                for formula in interactive["formulas"]
            ],
        }
    return data


def _render_limitations(packet: dict[str, Any], body: dict[str, Any]) -> list[str]:
    notes = [
        "本地报告不会发布到知乎。",
        "页面不加载外部资源，也不执行来源正文里的脚本。",
        packet["sample"]["note"],
    ]
    if body["workflow"] == "observe" and body.get("single_viewpoint"):
        notes.append("目前结构化结果里只有一种说法，不能并列成多个解释。")
    if body["workflow"] == "recent":
        notes.append("确认时间线只收有依据的事件日期。发布或更新时间单独显示，不自动当成事件日期。")
    notes.extend(packet.get("limitations") or [])
    return list(dict.fromkeys(notes))


def _walk_ids(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "evidence_ids" and isinstance(item, list):
                found.extend(part for part in item if isinstance(part, str))
            elif key == "evidence_id" and isinstance(item, str):
                found.append(item)
            else:
                found.extend(_walk_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_ids(item))
    return found


def _markdown(data: dict[str, Any]) -> str:
    state = "完整" if data["finished_research"] else "不完整"
    lines = [
        f"# {data['title']}",
        "",
        f"> {state}的本地研究报告。{data['sample_note']}",
        f"> {data['source_note']}",
        "",
        f"- 问题：{data['question']}",
        f"- 状态：{data['status']}",
    ]
    if data["incomplete_reason"]:
        lines.append(f"- 不完整原因：{data['incomplete_reason']}")
    lines.extend(["", "## 摘要", "", data["summary"], ""])
    if data["assumptions"]:
        lines.extend(["## 假设", ""])
        for item in data["assumptions"]:
            lines.append(f"- {item['id']}：{item['text']}")
        lines.append("")
    if data["conclusions"]:
        lines.extend(["## 有条件的结论", ""])
        for item in data["conclusions"]:
            lines.append(f"### {item['id']}")
            lines.append(f"- 条件：{item['condition']}")
            lines.append(f"- 结论：{item['text']}")
            lines.append(f"- 证据：{_join(item['evidence_ids'])}")
            lines.append(f"- 假设：{_join(item['assumption_ids'])}")
            lines.append("")
    sections = data["sections"]
    if "scenarios" in sections and sections["scenarios"]:
        lines.extend(["## 适用场景", ""])
        lines.extend(f"- {item}" for item in sections["scenarios"])
        lines.append("")
    if sections.get("comparisons"):
        lines.extend(["## 规格与体验", ""])
        for item in sections["comparisons"]:
            lines.append(f"### {item['topic']}")
            lines.append(f"- 规格：{item['spec']['text']}（{_join(item['spec']['evidence_ids'])}）")
            lines.append(
                f"- 体验：{item['experience']['text']}（{_join(item['experience']['evidence_ids'])}）"
            )
            lines.append("")
    if sections.get("disputes"):
        lines.extend(["## 并列争议", ""])
        for item in sections["disputes"]:
            lines.append(f"### {item['topic']}")
            for position in item["positions"]:
                lines.append(f"- {position['text']}（{_join(position['evidence_ids'])}）")
            lines.append("")
    if sections.get("viewpoints"):
        lines.extend(["## 并列观点", "", "这些是本次样本中的说法，不是全体用户观点。", ""])
        for item in sections["viewpoints"]:
            lines.append(f"- {item['text']}（{_join(item['evidence_ids'])}）")
        lines.append("")
    if sections.get("progress"):
        lines.extend(["## 进展", ""])
        for item in sections["progress"]:
            lines.append(f"- {item['text']}（{_join(item['evidence_ids'])}）")
        lines.append("")
    if sections.get("open_questions"):
        lines.extend(["## 未决问题", ""])
        for item in sections["open_questions"]:
            lines.append(f"- {item['text']}（{_join(item['evidence_ids'])}）")
        lines.append("")
    if "changes" in sections:
        lines.extend(["## 变化与影响", ""])
        for item in sections["changes"]:
            kind = "新信息" if item["kind"] == "new" else "影响"
            lines.append(f"- [{kind}] {item['text']}（{_join(item['evidence_ids'])}）")
        lines.append("")
        lines.extend(["## 确认的事件时间", ""])
        if not sections["confirmed_timeline"]:
            lines.append("没有通过校验的事件日期。缺日期的内容不会排进这里。")
        for item in sections["confirmed_timeline"]:
            lines.append(f"### {item['event_date']} {item['title']}")
            lines.append(f"- 依据：{item['event_date_basis']}")
            lines.append(f"- 影响：{item['impact']}")
            lines.append(f"- 证据：{_join(item['evidence_ids'])}")
            lines.extend(_publish_lines(item["evidence_ids"], data["cited_evidence"]))
            lines.append("")
        lines.extend(["## 日期不确定", ""])
        if not sections["uncertain_dates"]:
            lines.append("没有单独标出的不确定日期。")
        for item in sections["uncertain_dates"]:
            lines.append(f"- {item['title']}：{item['impact']}（{_join(item['evidence_ids'])}）")
            lines.extend(_publish_lines(item["evidence_ids"], data["cited_evidence"]))
        lines.extend(["", "## 后续核对", ""])
        lines.extend(f"- {item}" for item in sections["next_checks"])
        lines.append("")
    interactive = sections.get("interactive")
    if interactive:
        lines.extend(["## 可核对的计算", "", interactive["title"], ""])
        lines.append("下面是默认输入下的静态结果。拖动计算在 HTML 文件里，并且只使用这些输入。")
        lines.append("")
        for item in interactive["inputs"]:
            source = (
                f"证据 {item['evidence_id']}"
                if item["evidence_id"]
                else f"假设 {item['value_assumption_id']}"
            )
            lines.append(
                f"- {item['label']}：{item['value']} {item['unit']}；当前值来自{source}；"
                f"滑块范围来自假设 {item['bounds_assumption_id']}。"
            )
        for item in interactive.get("default_results") or []:
            lines.append(f"- {item['label']} = {item['display']} {item['unit']}")
        lines.append("")
    if data["conflicts"]:
        lines.extend(["## 证据冲突", ""])
        for item in data["conflicts"]:
            lines.append(f"- {item['topic']}：{item['note']}（{_join(item['evidence_ids'])}）")
        lines.append("")
    lines.extend(["## 来源摘录", ""])
    for item in data["cited_evidence"]:
        lines.append(f"### {item['id']} {item['title']}")
        lines.append(f"- 链接：{item.get('url') or '无'}")
        lines.append(f"- 文本类型：{item.get('text_kind')}；全文={item.get('full_text')}")
        if item.get("author"):
            lines.append(f"- 作者：{item['author']}")
        if item.get("vote_up_count") is not None:
            lines.append(f"- 赞同：{item['vote_up_count']}")
        authority = item.get("authority") or {}
        if authority.get("status") == "upstream":
            suffix = ""
            if authority.get("legend_applies"):
                suffix = f"，全网文档等级 {authority['legend']}"
            elif item.get("source") == "zhihu":
                suffix = "，不套用全网 1-4 说明"
            lines.append(f"- 权威等级原值：{authority.get('value')}{suffix}")
        else:
            lines.append("- 权威等级：上游未提供")
        timing = item.get("time") or {}
        lines.append(
            "- 发布或更新："
            f"{timing.get('publish_or_update_field') or '未提供'}"
            f" {timing.get('publish_or_update_unix') if timing.get('publish_or_update_unix') is not None else '未提供'}"
            "；事件时间：未由检索包推断"
        )
        if item.get("excerpt"):
            lines.extend(["", item["excerpt"]])
        lines.append("")
    lines.extend(["## 局限", ""])
    lines.extend(f"- {item}" for item in data["limitations"])
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _publish_lines(evidence_ids: list[str], evidence: list[dict[str, Any]]) -> list[str]:
    known = {item["id"]: item for item in evidence}
    lines = []
    for evidence_id in evidence_ids:
        item = known.get(evidence_id)
        if not item:
            continue
        timing = item.get("time") or {}
        unix = timing.get("publish_or_update_unix")
        if unix is None:
            lines.append(f"- {evidence_id} 的发布或更新时间：上游未提供")
        else:
            lines.append(
                f"- {evidence_id} 的发布或更新时间：{timing.get('publish_or_update_field')}={unix} "
                "（不是事件日期）"
            )
    return lines


def _html(data: dict[str, Any]) -> str:
    state = "资料不完整" if not data["finished_research"] else "已校验"
    parts = [
        "<!DOCTYPE html>",
        "<html lang=\"zh-CN\">",
        "<head>",
        "<meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; connect-src 'none'\">",
        f"<title>{_esc(data['title'])}</title>",
        "<style>",
        _CSS,
        "</style>",
        "</head>",
        "<body>",
        "<header>",
        f"<p class=\"state\">{_esc(state)}</p>",
        f"<h1>{_esc(data['title'])}</h1>",
        f"<p>{_esc(data['sample_note'])}</p>",
        "</header>",
        "<main>",
        f"<p class=\"note\">{_esc(data['source_note'])}</p>",
        f"<p><strong>问题</strong> {_esc(data['question'])}</p>",
        f"<section><h2>摘要</h2><p>{_esc(data['summary'])}</p></section>",
    ]
    parts.extend(_html_sections(data))
    parts.extend(["<section><h2>来源</h2>"])
    for item in data["cited_evidence"]:
        parts.append("<article>")
        parts.append(f"<h3>{_esc(item['id'])} {_esc(item['title'])}</h3>")
        url = item.get("url")
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            parts.append(f"<p><a href=\"{_esc(url)}\" rel=\"noreferrer noopener\">{_esc(url)}</a></p>")
        else:
            parts.append("<p>没有可用链接</p>")
        if item.get("author"):
            parts.append(f"<p>作者：{_esc(item['author'])}</p>")
        if item.get("vote_up_count") is not None:
            parts.append(f"<p>赞同：{_esc(item['vote_up_count'])}</p>")
        timing = item.get("time") or {}
        unix = timing.get("publish_or_update_unix")
        if unix is None:
            parts.append("<p>发布或更新时间：上游未提供。事件时间：检索包未推断。</p>")
        else:
            parts.append(
                "<p>发布或更新时间："
                f"{_esc(timing.get('publish_or_update_field'))}={_esc(unix)}。"
                "这不是事件日期。</p>"
            )
        if item.get("excerpt"):
            parts.append(f"<blockquote>{_esc(item['excerpt'])}</blockquote>")
        parts.append("</article>")
    parts.append("</section>")
    parts.append("<section><h2>局限</h2><ul>")
    for item in data["limitations"]:
        parts.append(f"<li>{_esc(item)}</li>")
    parts.extend(["</ul></section>", "</main>"])
    interactive = data["sections"].get("interactive")
    if interactive and all(item.get("ast") for item in interactive["formulas"]):
        parts.append(_script(interactive))
    parts.extend(["</body>", "</html>", ""])
    return "\n".join(parts)


def _html_sections(data: dict[str, Any]) -> list[str]:
    sections = data["sections"]
    parts: list[str] = []
    if data["conclusions"]:
        parts.append("<section><h2>有条件的结论</h2>")
        for item in data["conclusions"]:
            parts.append(
                "<article>"
                f"<h3>{_esc(item['id'])}</h3>"
                f"<p>条件：{_esc(item['condition'])}</p>"
                f"<p>{_esc(item['text'])}</p>"
                f"<p>证据 {_esc(_join(item['evidence_ids']))}</p>"
                "</article>"
            )
        parts.append("</section>")
    if sections.get("viewpoints"):
        parts.append("<section><h2>并列观点</h2><p>只覆盖本次检索样本。</p>")
        for item in sections["viewpoints"]:
            parts.append(f"<article><p>{_esc(item['text'])}</p><p>证据 {_esc(_join(item['evidence_ids']))}</p></article>")
        parts.append("</section>")
    if "confirmed_timeline" in sections:
        parts.append("<section><h2>确认的事件时间</h2>")
        if not sections["confirmed_timeline"]:
            parts.append("<p>没有通过校验的事件日期。</p>")
        for item in sections["confirmed_timeline"]:
            parts.append(
                "<article>"
                f"<h3>{_esc(item['event_date'])} {_esc(item['title'])}</h3>"
                f"<p>{_esc(item['impact'])}</p>"
                f"<p>依据：{_esc(item['event_date_basis'])}。证据 {_esc(_join(item['evidence_ids']))}</p>"
                "</article>"
            )
        parts.append("</section><section><h2>日期不确定</h2>")
        if not sections["uncertain_dates"]:
            parts.append("<p>没有单独标出的不确定日期。</p>")
        for item in sections["uncertain_dates"]:
            parts.append(f"<article><h3>{_esc(item['title'])}</h3><p>{_esc(item['impact'])}</p></article>")
        parts.append("</section>")
    interactive = sections.get("interactive")
    if interactive:
        parts.append(f"<section><h2>{_esc(interactive['title'])}</h2>")
        parts.append("<p>滑块范围是假设。当前值要么能在证据摘录中找到，要么另有假设编号。</p>")
        for item in interactive["inputs"]:
            source = item["evidence_id"] or item["value_assumption_id"]
            parts.append(
                "<label>"
                f"<span>{_esc(item['label'])}（{_esc(item['unit'])}）</span>"
                f"<input data-input=\"{_esc(item['id'])}\" type=\"range\" "
                f"min=\"{_esc(item['min'])}\" max=\"{_esc(item['max'])}\" "
                f"step=\"{_esc(item['step'])}\" value=\"{_esc(item['value'])}\">"
                f"<strong data-value=\"{_esc(item['id'])}\">{_esc(item['value'])}</strong>"
                "</label>"
                f"<p class=\"source\">当前值来源 {_esc(source)}；范围假设 {_esc(item['bounds_assumption_id'])}</p>"
            )
        for formula in interactive["formulas"]:
            display = format_number(formula["default_result"]) if isinstance(formula["default_result"], float) else "无法计算"
            parts.append(
                "<p class=\"result\">"
                f"<span>{_esc(formula['label'])}</span> "
                f"<output id=\"out-{_esc(formula['id'])}\">{_esc(display)}</output> "
                f"{_esc(formula['unit'])}"
                "</p>"
            )
        parts.append("</section>")
    return parts


def _script(interactive: dict[str, Any]) -> str:
    spec = {
        "formulas": [
            {"id": item["id"], "ast": item["ast"]}
            for item in interactive["formulas"]
        ]
    }
    payload = json.dumps(spec, ensure_ascii=False).replace("<", "\\u003c")
    return (
        "<script>\n"
        + INTERPRETER_JS
        + "\nfunction renderCalc() {\n"
        "  var spec = JSON.parse(document.getElementById('calc-spec').textContent);\n"
        "  var env = {};\n"
        "  var controls = document.querySelectorAll('[data-input]');\n"
        "  for (var i = 0; i < controls.length; i++) {\n"
        "    env[controls[i].getAttribute('data-input')] = Number(controls[i].value);\n"
        "    var mirror = document.querySelector('[data-value=\"' + controls[i].getAttribute('data-input') + '\"]');\n"
        "    if (mirror) mirror.textContent = controls[i].value;\n"
        "  }\n"
        "  for (var j = 0; j < spec.formulas.length; j++) {\n"
        "    var formula = spec.formulas[j];\n"
        "    var out = document.getElementById('out-' + formula.id);\n"
        "    if (out) out.textContent = formatNum(evalAst(formula.ast, env));\n"
        "  }\n"
        "}\n"
        "var controls = document.querySelectorAll('[data-input]');\n"
        "for (var i = 0; i < controls.length; i++) controls[i].addEventListener('input', renderCalc);\n"
        "renderCalc();\n"
        "</script>\n"
        f"<script id=\"calc-spec\" type=\"application/json\">{payload}</script>"
    )


_CSS = """
:root { color-scheme: light; }
body { margin: 0; background: #f3efe6; color: #221c16; font: 17px/1.65 "Iowan Old Style", "Palatino Linotype", Palatino, serif; }
header { background: #24352f; color: #f6f1e7; padding: 1.4rem 1.2rem 1.1rem; }
header h1 { font-size: 1.7rem; line-height: 1.3; margin: 0.2rem 0; }
main { max-width: 44rem; margin: 0 auto; padding: 1rem 1rem 3rem; }
section, article { background: #fffdf8; border: 1px solid #ddd4c4; border-radius: 8px; padding: 0.8rem 1rem; margin: 0.8rem 0; }
h2 { font-size: 1.15rem; margin: 0 0 0.4rem; }
a { color: #1d4e89; }
blockquote { margin: 0.4rem 0; white-space: pre-wrap; }
label { display: grid; grid-template-columns: 1fr auto; gap: 0.4rem 0.8rem; align-items: center; margin-top: 0.7rem; }
input[type="range"] { grid-column: 1 / -1; width: 100%; accent-color: #1f6f5b; }
.note, .source, .state { font-size: 0.92rem; }
.result output { font-variant-numeric: tabular-nums; font-weight: 700; }
"""


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _join(values: list[str]) -> str:
    return "、".join(values) if values else "无"


def _text(value: Any, path: str, check: _Check, *, limit: int, required: bool = True) -> str:
    if not isinstance(value, str):
        check.add(f"{path} 必须是字符串。")
        return ""
    if "\x00" in value:
        check.add(f"{path} 含有空字符。")
    stripped = value.strip()
    if required and not stripped:
        check.add(f"{path} 不能为空。")
    if len(value) > limit:
        check.add(f"{path} 超过 {limit} 个字符。")
    for phrase in _POPULATION:
        if phrase in value:
            check.add(f"{path} 不能把检索样本写成全体用户观点。")
            break
    return stripped


def _list(value: Any, path: str, check: _Check, *, limit: int) -> list[Any]:
    if not isinstance(value, list):
        check.add(f"{path} 必须是列表。")
        return []
    if len(value) > limit:
        check.add(f"{path} 超过 {limit} 项。")
        return value[:limit]
    return value


def _string_list(value: Any, path: str, check: _Check, *, limit: int) -> list[str]:
    items = _list(value, path, check, limit=limit)
    result = []
    for index, item in enumerate(items):
        result.append(_text(item, f"{path}[{index}]", check, limit=500))
    return result


def _ident(value: Any, path: str, check: _Check) -> str:
    if not isinstance(value, str) or not _IDENT.fullmatch(value):
        check.add(f"{path} 不合法。")
        return "invalid"
    return value


def _evidence_ids(
    value: Any,
    path: str,
    check: _Check,
    known: dict[str, dict[str, Any]],
    *,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        check.add(f"{path} 必须是证据 id 列表。")
        return []
    if not value and not allow_empty:
        check.add(f"{path} 不能为空。")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in known:
            check.add(f"{path} 引用了证据包中不存在的 id：{item}")
            continue
        if item not in result:
            result.append(item)
    return result


def _id_list(value: Any, path: str, check: _Check, allowed: set[str]) -> list[str]:
    if not isinstance(value, list):
        check.add(f"{path} 必须是列表。")
        return []
    result = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            check.add(f"{path} 引用了不存在的 id：{item}")
            continue
        if item not in result:
            result.append(item)
    return result


def _number(value: Any, path: str, check: _Check) -> float | None:
    if type(value) not in {int, float} or not math.isfinite(value):
        check.add(f"{path} 必须是有限数字。")
        return None
    return float(value)


def _number_in_text(number: float, text: str) -> bool:
    if float(number).is_integer():
        token = str(int(number))
    else:
        token = format(number, "g")
    return re.search(rf"(?<![\d.]){re.escape(token)}(?![\d.])", text) is not None


def _haystack(item: dict[str, Any]) -> str:
    return f"{item.get('title') or ''}\n{item.get('excerpt') or ''}"
