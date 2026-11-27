"""Bounded research retrieval over existing Zhihu Open Platform calls.

This module does not add an upstream endpoint and does not synthesize a
report. It plans a small set of searches, sends them through the shared
client (and therefore the existing call policy), and returns an evidence
packet. The host writes conclusions; ``research_render`` checks that write-up
and renders local files.

The product shape follows the public Zhihu data-platform description of
深度研究, 知乎观察 and 近况速览. The orchestration, field names and wording
are independent. Official skill text, renderers and styles are not reused.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from .upstream.base import InvalidArguments, McpError
from .upstream.http_client import ApiResult


SCHEMA = "zhihu-search.evidence.v1"
WORKFLOWS = ("deep", "observe", "recent")
SOURCES = ("zhihu", "web", "knowledge")
DEFAULT_SOURCES = {
    "deep": ("zhihu", "web"),
    "observe": ("zhihu",),
    "recent": ("zhihu", "web"),
}
DEFAULT_MAX_CALLS = 6
HARD_MAX_CALLS = 12
DEFAULT_COUNT = 5
MAX_COUNT = 10
MAX_ANGLES = 4
MAX_FOLLOW = 2
FOLLOW_ANSWER_LIMIT = 5
QUERY_MIN = 2
QUERY_MAX = 100
QUESTION_MAX = 500
WINDOW_MIN = 1
WINDOW_MAX = 90
DEFAULT_WINDOW_DAYS = 30
EXCERPT_LIMIT = 400
SHANGHAI = timezone(timedelta(hours=8))
PUBLISH_FIELDS = ("PublishTime", "publish_time", "PublishedAt", "published_at")
EDIT_FIELDS = ("EditTime", "edit_time")
CREATE_FIELDS = ("CreateTime", "create_time", "CreatedAt", "created_at")
GLOBAL_LEGEND = {"1": "low", "2": "medium", "3": "high", "4": "very_high"}
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
_QUESTION_PATH = re.compile(r"^/question/([1-9][0-9]{0,18})/?$")
_ANSWER_PATH = re.compile(r"^/question/([1-9][0-9]{0,18})/answer/[1-9][0-9]{0,18}/?$")
_ANSWER_SHORT_PATH = re.compile(r"^/answer/[0-9]+/?$")
_ARTICLE_PATH = re.compile(r"^/p/[0-9]+/?$")
_POLICY_MARKERS = (
    "已阻止",
    "免费额度",
    "每日业务调用上限",
    "额度预查失败",
    "额度映射未确认",
    "付费调用已阻止",
    "官方计费未确认",
    "保护锁",
    "调用记录",
)


@dataclass
class ResearchPlan:
    """A validated retrieval plan. Building it does not touch the network."""

    workflow: str
    question: str
    queries: list[str]
    sources: list[str]
    count: int
    max_calls: int
    window_days: int | None
    hosts: list[str]
    follow_questions: bool
    knowledge_base_ids: list[str] | None
    recall_scopes: list[str] | None
    clock_unix: int
    clock_source: str
    web_filter: str
    web_search_db: str | None
    notes: list[str] = field(default_factory=list)


def prepare(
    *,
    workflow: str,
    question: str,
    angles: list[str] | None = None,
    sources: list[str] | None = None,
    count: int = DEFAULT_COUNT,
    max_calls: int | None = None,
    window_days: int | None = None,
    hosts: list[str] | None = None,
    follow_questions: bool | None = None,
    knowledge_base_ids: list[str] | None = None,
    recall_scopes: list[str] | None = None,
    as_of: int | None = None,
    now: Callable[[], float] | None = None,
) -> ResearchPlan:
    """Validate a research request before any credential or network use."""
    if workflow not in WORKFLOWS:
        raise InvalidArguments("workflow 必须是 deep、observe 或 recent。")
    if not isinstance(question, str):
        raise InvalidArguments("question 必须是字符串。")
    question = question.strip()
    if not QUERY_MIN <= len(question) <= QUESTION_MAX:
        raise InvalidArguments(
            f"question 去除首尾空白后需要 {QUERY_MIN}-{QUESTION_MAX} 个字符。"
        )
    if type(count) is not int or not 1 <= count <= MAX_COUNT:
        raise InvalidArguments(f"count 必须是 1-{MAX_COUNT} 的整数。")
    if max_calls is None:
        max_calls = DEFAULT_MAX_CALLS
    if type(max_calls) is not int or not 1 <= max_calls <= HARD_MAX_CALLS:
        raise InvalidArguments(
            f"max_calls 是单次检索预算，必须是 1-{HARD_MAX_CALLS} 的整数，"
            "不能用来放宽每日上限或付费开关。"
        )
    if window_days is not None and (
        type(window_days) is not int or not WINDOW_MIN <= window_days <= WINDOW_MAX
    ):
        raise InvalidArguments(
            f"window_days 必须是 {WINDOW_MIN}-{WINDOW_MAX} 的整数。"
        )

    queries = _queries(question, angles)
    selected = _sources(workflow, sources)
    base_ids = _clean_list(knowledge_base_ids)
    scopes = _clean_list(recall_scopes)
    notes: list[str] = []
    if base_ids or scopes:
        if sources is not None and "knowledge" not in selected:
            raise InvalidArguments(
                "已经提供知识库或召回范围，但 sources 没有包含 knowledge。"
            )
        if "knowledge" not in selected:
            selected.append("knowledge")
    if "knowledge" in selected and not base_ids and not scopes:
        raise InvalidArguments(
            "knowledge 需要 knowledge_base_ids 或 recall_scopes；不会猜测知识库。"
        )

    cleaned_hosts = _hosts(hosts)
    if cleaned_hosts and "web" not in selected:
        raise InvalidArguments("host 只用于全网搜索；当前 sources 没有 web。")

    if follow_questions is None:
        follow_questions = workflow == "observe"
    if type(follow_questions) is not bool:
        raise InvalidArguments("follow_questions 必须是布尔值。")
    if workflow == "recent" and follow_questions:
        follow_questions = False
        notes.append("recent 不追问题回答摘要；日期窗口只来自检索参数和上游时间字段。")
    if window_days is not None and workflow != "recent":
        notes.append("window_days 只在 recent 生效；本次没有按日期过滤。")
        window_days = None
    if workflow == "recent" and window_days is None:
        window_days = DEFAULT_WINDOW_DAYS

    clock_source = "argument" if as_of is not None else "system"
    if as_of is None:
        clock_unix = int((now or time.time)())
    else:
        if type(as_of) is not int or not 946684800 <= as_of <= 4102444800:
            raise InvalidArguments("as_of 必须是 2000-01-01 到 2100-01-01 之间的 Unix 秒。")
        clock_unix = as_of

    web_filter = ""
    web_search_db: str | None = None
    if "web" in selected:
        start = None
        if workflow == "recent" and window_days is not None:
            start = clock_unix - window_days * 86400
            web_search_db = "realtime"
        else:
            web_search_db = "all"
        web_filter = _web_filter(cleaned_hosts, start)

    return ResearchPlan(
        workflow=workflow,
        question=question,
        queries=queries,
        sources=selected,
        count=count,
        max_calls=max_calls,
        window_days=window_days,
        hosts=cleaned_hosts,
        follow_questions=follow_questions,
        knowledge_base_ids=base_ids or None,
        recall_scopes=scopes or None,
        clock_unix=clock_unix,
        clock_source=clock_source,
        web_filter=web_filter,
        web_search_db=web_search_db,
        notes=notes,
    )


async def execute(plan: ResearchPlan, client: Any) -> dict[str, Any]:
    """Run the plan on an existing client. Failures are recorded, not retried."""
    jobs = _search_jobs(plan)
    calls: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    failures: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    limitations = list(plan.notes)
    stopped = False
    stop_kind: str | None = None

    sendable = jobs[: plan.max_calls]
    held = jobs[plan.max_calls :]
    for job in sendable:
        if stopped:
            calls.append(_not_sent(job, "已停止：失败后不自动重试，也不继续发送。"))
            continue
        outcome = await _dispatch(client, job)
        calls.append(outcome["call"])
        if outcome["error"]:
            failures.append(outcome["error"])
            stopped = True
            stop_kind = outcome["stop_kind"]
            continue
        if outcome.get("items_shape") == "missing":
            limitations.append(
                f"{job['endpoint']} 对「{job['query']}」返回了成功响应，但没有 Items 列表。"
                "这不是一份结构完整的空结果。"
            )
        else:
            _absorb(
                outcome.get("items") or [],
                job,
                plan,
                evidence,
                duplicates,
                seen,
                limitations,
            )
    for job in held:
        calls.append(_not_sent(job, "超出本次 max_calls，未发送。"))

    if plan.follow_questions and not stopped:
        await _follow_questions(
            client,
            plan,
            evidence,
            duplicates,
            seen,
            calls,
            failures,
            traces,
            limitations,
        )
        if failures:
            stopped = True
            stop_kind = failures[-1]["stop_kind"]
    elif plan.follow_questions and stopped:
        limitations.append("检索在追问前停止，未调用 question_answers。")

    if not plan.follow_questions and plan.workflow in {"deep", "observe"}:
        limitations.append(
            "未调用 question_answers。搜索结果里的链接可以人工打开；"
            "回答摘要不是默认取回的。"
        )

    succeeded = sum(call["status"] == "ok" for call in calls)
    failed = sum(call["status"] == "error" for call in calls)
    not_sent = sum(call["status"] == "not_sent" for call in calls)
    truncated = any(call.get("has_more") is True for call in calls) or any(
        trace.get("status") == "ok" and trace.get("answers_page_complete") is not True
        for trace in traces
    )
    malformed = any(call.get("items_shape") == "missing" for call in calls)
    if truncated:
        limitations.append(
            "上游标记还有更多结果，但没有可用的翻页参数，或回答摘要不是最后一页。"
            "本次没有继续请求。"
        )
    if malformed:
        limitations.append("缺少 Items 的成功响应没有被当成空结果。")
    if succeeded == 0:
        status = "blocked"
    elif failed or not_sent or truncated or malformed:
        status = "partial"
    else:
        status = "complete"
    if stop_kind is None and not_sent:
        stop_kind = "budget"

    window_start = None
    if plan.window_days is not None:
        window_start = plan.clock_unix - plan.window_days * 86400
    chronology = _chronology(evidence, plan.workflow)
    limitations.extend(_fixed_limitations(plan.workflow))
    packet = {
        "schema": SCHEMA,
        "role": "evidence",
        "finished_research": False,
        "ask_used": False,
        "workflow": plan.workflow,
        "question": plan.question,
        "status": status,
        "generated_at_unix": plan.clock_unix,
        "timezone": "Asia/Shanghai",
        "synthesis": {
            "status": "not_synthesized",
            "report": None,
            "html": None,
            "numeric_claims": [],
            "owner": "host",
        },
        "render": {
            "status": "not_rendered",
            "command": "zhihu-search research-render EVIDENCE.json SYNTHESIS.json --out DIR",
            "note": (
                "本对象是检索证据，不是研究报告，也不是交互页面。"
                "宿主写出 zhihu-search.report.v1 后，由 research-render 校验并生成本地文件。"
            ),
        },
        "sample": {
            "scope": "search_sample",
            "population_claim": False,
            "note": "这些条目只是本次检索返回的样本，不是知乎全体用户的观点。",
        },
        "budget": {
            "max_calls": plan.max_calls,
            "planned": 0,
            "attempted": succeeded + failed,
            "succeeded": succeeded,
            "failed": failed,
            "not_sent": not_sent,
            "retry": False,
            "stop_reason": stop_kind,
            "daily_cap_unchanged": True,
            "paid_switch_unchanged": True,
        },
        "dates": {
            "timezone": "Asia/Shanghai",
            "clock_unix": plan.clock_unix,
            "clock_source": plan.clock_source,
            "window_days": plan.window_days,
            "window_start_unix": window_start,
            "window_end_unix": plan.clock_unix if window_start is not None else None,
            "web_filter": plan.web_filter or None,
            "web_search_db": plan.web_search_db,
            "zhihu_date_filter": False,
            "ranking_is_time": False,
        },
        "calls": calls,
        "failures": [
            {key: value for key, value in item.items() if key != "stop_kind"}
            for item in failures
        ],
        "evidence": evidence,
        "duplicates": duplicates,
        "question_traces": traces,
        "chronology": chronology,
        "limitations": _unique(limitations),
    }
    packet["budget"]["planned"] = len(calls)
    _number_calls(packet)
    return packet


def format_evidence_packet(data: dict[str, Any] | None) -> str:
    """Markdown view of an evidence packet. It never reads like a finished report."""
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return "（没有可展示的研究证据包）"
    workflow = {"deep": "深度研究", "observe": "知乎观察", "recent": "近况速览"}.get(
        str(data.get("workflow")), str(data.get("workflow"))
    )
    lines = [
        "## 检索证据包",
        "",
        "这不是研究报告，也不是交互页面。`report` 与 `html` 均为 null。",
        "结论、观点并列、事件时间和交互计算由宿主写入结构化结果，再交给 research-render。",
        "",
        f"- 工作流：{workflow}",
        f"- 问题：{data.get('question') or ''}",
        f"- 状态：{data.get('status')}",
        f"- 样本：{data.get('sample', {}).get('note', '')}",
        "",
        "### 预算",
    ]
    budget = data.get("budget") if isinstance(data.get("budget"), dict) else {}
    lines.append(
        "- 计划发送 {attempted} 次已执行（成功 {succeeded}，失败 {failed}，未发送 {not_sent}），"
        "单次上限 {max_calls}。不自动重试。".format(
            attempted=budget.get("attempted"),
            succeeded=budget.get("succeeded"),
            failed=budget.get("failed"),
            not_sent=budget.get("not_sent"),
            max_calls=budget.get("max_calls"),
        )
    )
    if budget.get("stop_reason"):
        lines.append(f"- 停止原因：{budget['stop_reason']}")
    dates = data.get("dates") if isinstance(data.get("dates"), dict) else {}
    lines.extend(["", "### 日期", ""])
    lines.append(
        f"- 时钟：{dates.get('clock_unix')}（{dates.get('clock_source')}，Asia/Shanghai）"
    )
    lines.append(f"- 窗口天数：{dates.get('window_days')}")
    lines.append(f"- 全网 Filter：{dates.get('web_filter') or '无'}")
    lines.append(f"- 全网 SearchDB：{dates.get('web_search_db') or '无'}")
    lines.append("- 知乎搜索没有日期参数。搜索排名不表示时间。")
    chronology = data.get("chronology") if isinstance(data.get("chronology"), dict) else {}
    lines.append(f"- 说明：{chronology.get('note') or ''}")
    lines.extend(["", "### 调用", ""])
    for call in data.get("calls") or []:
        if not isinstance(call, dict):
            continue
        lines.append(
            f"- {call.get('id')} {call.get('endpoint')} [{call.get('status')}] "
            f"{call.get('query')}"
        )
        if call.get("filter"):
            lines.append(f"  - Filter：{call['filter']}")
        if call.get("error"):
            lines.append(f"  - 错误：{call['error']}")
        if call.get("reason"):
            lines.append(f"  - 原因：{call['reason']}")
    lines.extend(["", "### 证据", ""])
    items = data.get("evidence") if isinstance(data.get("evidence"), list) else []
    if not items:
        lines.append("没有取回证据。")
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.extend(_format_item(item))
    lines.extend(["", "### 局限", ""])
    for note in data.get("limitations") or []:
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "下一步：宿主依据证据编号撰写 `zhihu-search.report.v1`，然后运行",
            "`zhihu-search research-render EVIDENCE.json SYNTHESIS.json --out DIR`。",
            "不要把本段保存成报告或发布到知乎。",
        ]
    )
    return "\n".join(lines).rstrip()


def _queries(question: str, angles: list[str] | None) -> list[str]:
    if angles is None:
        angles = []
    if not isinstance(angles, list):
        raise InvalidArguments("angles 必须是字符串列表。")
    cleaned: list[str] = []
    for raw in angles:
        if not isinstance(raw, str):
            raise InvalidArguments("每个 angle 必须是字符串。")
        text = raw.strip()
        if not text:
            continue
        if not QUERY_MIN <= len(text) <= QUERY_MAX:
            raise InvalidArguments(
                f"angle 需要 {QUERY_MIN}-{QUERY_MAX} 个字符：{text[:40]}"
            )
        if text not in cleaned:
            cleaned.append(text)
    if len(cleaned) > MAX_ANGLES:
        raise InvalidArguments(f"angle 最多 {MAX_ANGLES} 个。")
    if cleaned:
        return cleaned
    if len(question) > QUERY_MAX:
        raise InvalidArguments(
            "问题长于 100 个字符。宿主需要先把它拆成 2-100 字的 angle，"
            "工具不会擅自截断后拿去搜索。"
        )
    return [question]


def _sources(workflow: str, sources: list[str] | None) -> list[str]:
    if sources is None:
        return list(DEFAULT_SOURCES[workflow])
    if not isinstance(sources, list) or not sources:
        raise InvalidArguments("sources 必须是非空列表。")
    selected: list[str] = []
    for source in sources:
        if source not in SOURCES:
            raise InvalidArguments(
                "未知 source。只能是 zhihu、web、knowledge，不能发明新的检索端点。"
            )
        if source not in selected:
            selected.append(source)
    return [source for source in SOURCES if source in selected]


def _clean_list(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise InvalidArguments("列表参数必须是字符串列表。")
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise InvalidArguments("列表项必须是非空字符串。")
        text = value.strip()
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def _hosts(hosts: list[str] | None) -> list[str]:
    cleaned = _clean_list(hosts)
    normalized: list[str] = []
    for host in cleaned:
        lowered = host.lower().rstrip(".")
        if not _HOST_RE.fullmatch(lowered):
            raise InvalidArguments(f"host 不是可用的域名：{host}")
        if lowered == "zhihu.com" or lowered.endswith(".zhihu.com"):
            raise InvalidArguments("全网 Filter 不能用来限定 zhihu.com。")
        if lowered not in normalized:
            normalized.append(lowered)
    return normalized


def _web_filter(hosts: list[str], start: int | None) -> str:
    parts: list[str] = []
    if hosts:
        host_expr = " OR ".join(f'host=="{host}"' for host in hosts)
        if len(hosts) > 1:
            host_expr = f"({host_expr})"
        parts.append(host_expr)
    if start is not None:
        parts.append(f"publish_time>={start}")
    return " AND ".join(parts)


def _search_jobs(plan: ResearchPlan) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for query in plan.queries:
        for source in plan.sources:
            job: dict[str, Any] = {
                "source": source,
                "query": query,
                "count": plan.count,
            }
            if source == "zhihu":
                job.update(endpoint="zhihu_search", filter="", search_db=None)
            elif source == "web":
                job.update(
                    endpoint="global_search",
                    filter=plan.web_filter,
                    search_db=plan.web_search_db,
                )
            else:
                job.update(
                    endpoint="knowledge_search",
                    filter="",
                    search_db=None,
                    knowledge_base_ids=plan.knowledge_base_ids,
                    recall_scopes=plan.recall_scopes,
                )
            jobs.append(job)
    return jobs


def _not_sent(job: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "id": "",
        "source": job["source"],
        "endpoint": job["endpoint"],
        "query": job["query"],
        "status": "not_sent",
        "filter": job.get("filter") or "",
        "search_db": job.get("search_db"),
        "count": job.get("count"),
        "error": None,
        "reason": reason,
        "has_more": None,
        "item_count": None,
        "items_shape": "not_applicable",
    }


async def _dispatch(client: Any, job: dict[str, Any]) -> dict[str, Any]:
    try:
        if job["endpoint"] == "zhihu_search":
            result = await client.zhihu_search(query=job["query"], count=job["count"])
        elif job["endpoint"] == "global_search":
            result = await client.global_search(
                query=job["query"],
                count=job["count"],
                filter=job.get("filter") or "",
                search_db=job.get("search_db") or "all",
            )
        else:
            result = await client.knowledge_search(
                job["query"],
                knowledge_base_ids=job.get("knowledge_base_ids"),
                recall_scopes=job.get("recall_scopes"),
                limit=job["count"],
            )
    except McpError as exc:
        message = str(exc)
        return {
            "call": _call(job, "error", error=message),
            "error": _failure(job, message),
            "stop_kind": "call_policy" if _policy(message) else "upstream_error",
            "data": None,
        }
    except Exception as exc:
        message = f"未预期错误：{exc}"
        return {
            "call": _call(job, "error", error=message),
            "error": _failure(job, message),
            "stop_kind": "upstream_error",
            "data": None,
        }
    data = result.data if isinstance(result, ApiResult) else getattr(result, "data", None)
    shape, items = _read_items(data)
    has_more = data.get("HasMore") if isinstance(data, dict) else None
    if not isinstance(has_more, bool):
        has_more = None
    return {
        "call": _call(
            job,
            "ok",
            has_more=has_more,
            item_count=len(items) if shape == "list" else None,
            items_shape=shape,
        ),
        "error": None,
        "stop_kind": None,
        "data": data,
        "items": items,
        "items_shape": shape,
    }


def _call(
    job: dict[str, Any],
    status: str,
    *,
    error: str | None = None,
    has_more: bool | None = None,
    item_count: int | None = None,
    items_shape: str = "not_applicable",
) -> dict[str, Any]:
    return {
        "id": "",
        "source": job["source"],
        "endpoint": job["endpoint"],
        "query": job["query"],
        "status": status,
        "filter": job.get("filter") or "",
        "search_db": job.get("search_db"),
        "count": job.get("count"),
        "error": error,
        "reason": None,
        "has_more": has_more,
        "item_count": item_count,
        "items_shape": items_shape,
    }


def _failure(job: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "source": job["source"],
        "endpoint": job["endpoint"],
        "query": job["query"],
        "error": message,
        "retried": False,
        "stop_kind": "call_policy" if _policy(message) else "upstream_error",
    }


def _policy(message: str) -> bool:
    return any(marker in message for marker in _POLICY_MARKERS)


def _absorb(
    items: list[dict[str, Any]],
    job: dict[str, Any],
    plan: ResearchPlan,
    evidence: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
    seen: dict[str, str],
    limitations: list[str],
) -> None:
    for rank, item in enumerate(items, 1):
        if job["source"] == "knowledge":
            normalized = _knowledge_item(item, job, rank, plan)
        else:
            normalized = _search_item(item, job, rank, plan)
        _keep(normalized, evidence, duplicates, seen)
    if not items:
        limitations.append(
            f"{job['endpoint']} 对「{job['query']}」返回了空的 Items 列表。"
        )


def _keep(
    item: dict[str, Any],
    evidence: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
    seen: dict[str, str],
) -> str:
    """Return the evidence id that preserves this record.

    The same canonical URL with a different text kind or a different excerpt
    stays as its own record. Identical repeats point at the earlier id.
    """
    key = item.pop("_dedupe")
    previous = seen.get(key)
    if previous:
        kept = next(entry for entry in evidence if entry["id"] == previous)
        if kept.get("excerpt") != item.get("excerpt") or kept.get("text_kind") != item.get("text_kind"):
            item["id"] = f"e{len(evidence) + 1}"
            item["same_locator_as"] = previous
            evidence.append(item)
            duplicates.append(
                {
                    "kept_id": previous,
                    "also_kept_id": item["id"],
                    "reason": "excerpt_differs",
                    "source": item["source"],
                    "query": item["query"],
                    "search_rank": item["search_rank"],
                    "url": item["url"],
                }
            )
            return item["id"]
        duplicates.append(
            {
                "kept_id": previous,
                "source": item["source"],
                "query": item["query"],
                "search_rank": item["search_rank"],
                "url": item["url"],
            }
        )
        return previous
    item["id"] = f"e{len(evidence) + 1}"
    seen[key] = item["id"]
    evidence.append(item)
    return item["id"]


def _search_item(
    item: dict[str, Any],
    job: dict[str, Any],
    rank: int,
    plan: ResearchPlan,
    *,
    text_kind: str = "upstream_excerpt",
    excerpt: str | None = None,
) -> dict[str, Any]:
    url = _clean_url(_first(item, "Url", "url"))
    if excerpt is None:
        excerpt = _excerpt(_first(item, "ContentText", "Summary", "summary"))
    token = _text(_first(item, "ContentToken", "content_token"))
    return _record(
        source=job["source"],
        endpoint=job["endpoint"],
        query=job["query"],
        rank=rank,
        title=_text(_first(item, "Title", "title")) or "(无标题)",
        url=url,
        author=_author(item),
        votes=_int_field(item, "VoteUpCount", "vote_up_count"),
        excerpt=excerpt,
        text_kind=text_kind,
        full_text=False,
        authority=_authority(item, job["source"]),
        ranking=_ranking(item, job["source"]),
        content_type=_text(_first(item, "ContentType", "content_type")),
        raw_item=item,
        plan=plan,
        dedupe=_identity(url, text_kind, _text(_first(item, "Title", "title")) or "", excerpt, token),
    )


def _knowledge_item(
    item: dict[str, Any],
    job: dict[str, Any],
    rank: int,
    plan: ResearchPlan,
) -> dict[str, Any]:
    content = item.get("Content") if "Content" in item else item.get("content")
    if isinstance(content, list):
        excerpt = _excerpt("\n".join(str(part) for part in content if str(part).strip()))
    else:
        excerpt = _excerpt(content if isinstance(content, str) else "")
    title = _text(_first(item, "DocName", "doc_name")) or "(未命名文档)"
    url = _clean_url(_first(item, "OriginUrl", "origin_url"))
    token = _text(_first(item, "RecallContentID", "recall_content_id", "RecallContentId"))
    return _record(
        source="knowledge",
        endpoint="knowledge_search",
        query=job["query"],
        rank=rank,
        title=title,
        url=url,
        author=None,
        votes=None,
        excerpt=excerpt,
        text_kind="knowledge_snippet",
        full_text=False,
        authority=_authority(item, "knowledge"),
        ranking={"status": "not_provided", "value": None},
        content_type=None,
        raw_item=item,
        plan=plan,
        dedupe=_identity(url, "knowledge_snippet", title, excerpt, token),
    )


def _record(
    *,
    source: str,
    endpoint: str,
    query: str,
    rank: int,
    title: str,
    url: str | None,
    author: str | None,
    votes: int | None,
    excerpt: str,
    text_kind: str,
    full_text: bool,
    authority: dict[str, Any],
    ranking: dict[str, Any],
    content_type: str | None,
    raw_item: dict[str, Any],
    plan: ResearchPlan,
    dedupe: str,
) -> dict[str, Any]:
    times = _times(raw_item, source)
    timing = _describe_time(times, source, plan)
    record = {
        "source": source,
        "endpoint": endpoint,
        "query": query,
        "search_rank": rank,
        "title": title,
        "url": url,
        "author": author,
        "vote_up_count": votes,
        "content_type": content_type,
        "excerpt": excerpt,
        "text_kind": text_kind,
        "full_text": full_text,
        "authority": authority,
        "ranking_score": ranking,
        "time": timing,
        "upstream_times": [
            {
                "field": item["field"],
                "raw": item["raw"],
                "unix": item["unix"],
                "status": item["status"],
                "role": item["role"],
            }
            for item in times
        ],
        "_dedupe": dedupe,
    }
    return record


def _authority(item: dict[str, Any], source: str) -> dict[str, Any]:
    for key in ("AuthorityLevel", "authority_level"):
        if key in item and item[key] not in (None, ""):
            value = item[key]
            legend = None
            applies = False
            if source == "web" and isinstance(value, str) and value in GLOBAL_LEGEND:
                legend = GLOBAL_LEGEND[value]
                applies = True
            return {
                "status": "upstream",
                "field": key,
                "value": value,
                "legend": legend,
                "legend_applies": applies,
            }
    return {
        "status": "not_provided",
        "field": None,
        "value": None,
        "legend": None,
        "legend_applies": False,
    }


def _ranking(item: dict[str, Any], source: str) -> dict[str, Any]:
    if source != "zhihu" or "RankingScore" not in item:
        return {"status": "not_provided", "value": None}
    value = item["RankingScore"]
    if type(value) is not int and type(value) is not float:
        return {"status": "unusable", "value": None}
    return {"status": "upstream", "value": value}


def _time_entry(field: str, raw: Any, role: str) -> dict[str, Any]:
    unix = _unix(raw)
    if isinstance(raw, str) or type(raw) is int:
        preserved = raw
    else:
        preserved = None
    return {
        "field": field,
        "raw": preserved,
        "unix": unix,
        "status": "usable" if unix is not None else "unusable",
        "role": role,
    }


def _times(item: dict[str, Any], source: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for key in PUBLISH_FIELDS:
        if key in item:
            found.append(_time_entry(key, item[key], "returned_publish_time"))
    for key in EDIT_FIELDS:
        if key not in item:
            continue
        if source == "zhihu":
            role = "publish_or_update"
        elif source == "web":
            role = "last_edit"
        else:
            role = "upstream_edit_time"
        found.append(_time_entry(key, item[key], role))
    for key in CREATE_FIELDS:
        if key in item:
            found.append(_time_entry(key, item[key], "create_time"))
    return found


def _usable(times: list[dict[str, Any]], role: str) -> dict[str, Any] | None:
    return next((item for item in times if item["role"] == role and item["status"] == "usable"), None)


def _any_role(times: list[dict[str, Any]], role: str) -> dict[str, Any] | None:
    return next((item for item in times if item["role"] == role), None)


def _describe_time(
    times: list[dict[str, Any]],
    source: str,
    plan: ResearchPlan,
) -> dict[str, Any]:
    """Label upstream clocks without treating EditTime as a publish_time filter."""
    publish = _usable(times, "returned_publish_time")
    edited = _usable(times, "publish_or_update") or _usable(times, "last_edit") or _usable(times, "upstream_edit_time")
    created = _any_role(times, "create_time")
    filter_sent = source == "web" and "publish_time" in (plan.web_filter or "")

    def inside(unix: int) -> bool | None:
        if plan.workflow != "recent" or plan.window_days is None:
            return None
        start = plan.clock_unix - plan.window_days * 86400
        return start <= unix <= plan.clock_unix

    bucket = "not_applicable"
    note = "本次不是按日期窗口整理。"
    in_window = None
    if plan.workflow == "recent":
        if source == "web" and filter_sent and publish is None:
            bucket = "publish_filter_not_verifiable"
            note = (
                "请求带了 publish_time 过滤，但返回条目没有可核对的 publish_time 字段。"
                "全网 EditTime 是最后编辑时间，不能证明服务端按发布时间过滤。"
            )
        elif publish is not None:
            in_window = inside(publish["unix"])
            bucket = (
                "returned_publish_time_in_window"
                if in_window
                else "returned_publish_time_outside_window"
            )
            note = "这是返回字段与窗口的本地比较，不是对服务端过滤的审计，也不是事件时间。"
        elif edited is not None and edited["role"] == "publish_or_update":
            in_window = inside(edited["unix"])
            bucket = (
                "local_publish_or_update_in_window"
                if in_window
                else "local_publish_or_update_outside_window"
            )
            note = "知乎 EditTime 是发布或更新时间。站内请求没有 publish_time 参数，窗口只在本地比较。"
        elif edited is not None:
            in_window = inside(edited["unix"])
            bucket = (
                "local_last_edit_in_window"
                if in_window
                else "local_last_edit_outside_window"
            )
            note = "这是编辑时间的本地比较，不能证明 publish_time 过滤，也不是事件时间。"
        else:
            bucket = "undated"
            note = "没有可用的上游时间字段。"
    publish_or_update = _usable(times, "publish_or_update")
    return {
        "publish_or_update_unix": publish_or_update["unix"] if publish_or_update else None,
        "publish_or_update_field": publish_or_update["field"] if publish_or_update else None,
        "publish_or_update_role": "publish_or_update" if publish_or_update else None,
        "last_edit_unix": edited["unix"] if edited and edited["role"] == "last_edit" else None,
        "last_edit_field": edited["field"] if edited and edited["role"] == "last_edit" else None,
        "create_time": {
            "status": created["status"] if created else "not_provided",
            "field": created["field"] if created else None,
            "raw": created["raw"] if created else None,
            "unix": created["unix"] if created else None,
        },
        "returned_publish_time": {
            "status": "usable" if publish else "not_provided",
            "field": publish["field"] if publish else None,
            "unix": publish["unix"] if publish else None,
        },
        "event_unix": None,
        "event_status": "not_provided",
        "in_requested_window": in_window if publish is not None else None,
        "server_publish_filter_sent": filter_sent,
        "server_publish_filter_verified_by_item": False,
        "bucket": bucket,
        "bucket_note": note,
    }


def _unix(value: Any) -> int | None:
    if type(value) is int and 0 < value <= 10**11:
        return value
    return None


def _chronology(evidence: list[dict[str, Any]], workflow: str) -> dict[str, Any]:
    groups: dict[str, list[str]] = {
        "returned_publish_time_in_window": [],
        "local_time_in_window": [],
        "outside_window": [],
        "publish_filter_not_verifiable": [],
        "undated": [],
    }
    if workflow == "recent":
        returned = []
        local = []
        for item in evidence:
            bucket = item["time"]["bucket"]
            if bucket == "returned_publish_time_in_window":
                returned.append(item)
            elif bucket in {"local_publish_or_update_in_window", "local_last_edit_in_window"}:
                local.append(item)
            elif bucket in {
                "returned_publish_time_outside_window",
                "local_publish_or_update_outside_window",
                "local_last_edit_outside_window",
            }:
                groups["outside_window"].append(item["id"])
            elif bucket == "publish_filter_not_verifiable":
                groups["publish_filter_not_verifiable"].append(item["id"])
            elif bucket == "undated":
                groups["undated"].append(item["id"])
        returned.sort(key=lambda item: (item["time"]["returned_publish_time"]["unix"], item["id"]))
        local.sort(key=_local_time_sort)
        groups["returned_publish_time_in_window"] = [item["id"] for item in returned]
        groups["local_time_in_window"] = [item["id"] for item in local]
    return {
        "confirmed_events": [],
        **groups,
        "note": (
            "confirmed_events 在检索阶段始终为空。返回的 publish_time 或 EditTime"
            "落在窗口内不是事件时间。EditTime 不能证明服务端 publish_time 过滤。"
            "搜索排名不参与排序。"
        ),
    }


def _local_time_sort(item: dict[str, Any]) -> tuple[int, str]:
    timing = item["time"]
    unix = timing.get("publish_or_update_unix")
    if unix is None:
        unix = timing.get("last_edit_unix")
    return (unix if isinstance(unix, int) else 0, item["id"])


async def _follow_questions(
    client: Any,
    plan: ResearchPlan,
    evidence: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
    seen: dict[str, str],
    calls: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    limitations: list[str],
) -> None:
    remaining = plan.max_calls - sum(call["status"] != "not_sent" for call in calls)
    questions: list[tuple[str, list[str]]] = []
    unsupported: list[str] = []
    for item in evidence:
        kind, question = _follow_target(item.get("url"))
        if kind == "question" and question:
            matched = next((entry for entry in questions if entry[0] == question), None)
            if matched:
                matched[1].append(item["id"])
            else:
                questions.append((question, [item["id"]]))
        elif kind == "unsupported" and item.get("url"):
            unsupported.append(str(item["url"]))
    if unsupported:
        shown = "、".join(unsupported[:4])
        limitations.append(
            "这些链接不能用 question_answers 追溯："
            f"{shown}。该接口只接受 https://www.zhihu.com/question/{{id}} "
            "及问题下的 https://www.zhihu.com/question/{{qid}}/answer/{{aid}} 链接。"
            "单独的 /answer/{{id}} 和专栏链接没有已接入的反查接口，本次不编造。"
        )
    if not questions:
        limitations.append("结果里没有可识别的知乎问题链接，未调用 question_answers。")
        return
    chosen = questions[: min(MAX_FOLLOW, max(remaining, 0))]
    skipped = questions[len(chosen) :]
    for url, parents in skipped:
        calls.append(
            _not_sent(
                {
                    "source": "question_answers",
                    "endpoint": "question_answers",
                    "query": url,
                    "filter": "",
                    "search_db": None,
                    "count": FOLLOW_ANSWER_LIMIT,
                },
                "超出本次 max_calls，未取回答摘要。",
            )
        )
        traces.append(
            {
                "question_url": url,
                "from_evidence_ids": parents,
                "answer_evidence_ids": [],
                "answers_page_complete": None,
                "text_kind": "upstream_summary",
                "status": "not_sent",
            }
        )
    failed = False
    for url, parents in chosen:
        job = {
            "source": "question_answers",
            "endpoint": "question_answers",
            "query": url,
            "filter": "",
            "search_db": None,
            "count": FOLLOW_ANSWER_LIMIT,
        }
        if failed:
            calls.append(_not_sent(job, "已停止：失败后不自动重试，也不继续发送。"))
            continue
        try:
            result = await client.question_answers(url, offset=0, limit=FOLLOW_ANSWER_LIMIT)
        except McpError as exc:
            message = str(exc)
            calls.append(_call(job, "error", error=message))
            failures.append(_failure(job, message))
            failed = True
            continue
        except Exception as exc:
            message = f"未预期错误：{exc}"
            calls.append(_call(job, "error", error=message))
            failures.append(_failure(job, message))
            failed = True
            continue
        data = result.data if isinstance(result, ApiResult) else getattr(result, "data", None)
        shape, items = _read_items(data)
        paging = data.get("Paging") if isinstance(data, dict) and isinstance(data.get("Paging"), dict) else {}
        is_end = paging.get("IsEnd")
        complete = is_end if isinstance(is_end, bool) else None
        if shape == "missing":
            complete = None
            limitations.append(f"{url} 的回答响应没有 Items 列表，不能当成没有回答。")
        calls.append(
            _call(
                job,
                "ok",
                has_more=False if complete else None if complete is None else True,
                item_count=len(items) if shape == "list" else None,
                items_shape=shape,
            )
        )
        answer_ids: list[str] = []
        for rank, item in enumerate(items, 1):
            record = _search_item(
                item,
                {**job, "source": "question_answers"},
                rank,
                plan,
                text_kind="upstream_summary",
                excerpt=_excerpt(_first(item, "Summary", "summary", "ContentText")),
            )
            record["full_text"] = False
            answer_ids.append(_keep(record, evidence, duplicates, seen))
        traces.append(
            {
                "question_url": url,
                "from_evidence_ids": parents,
                "answer_evidence_ids": answer_ids,
                "answers_page_complete": complete,
                "text_kind": "upstream_summary",
                "status": "ok",
            }
        )
        if complete is not True:
            limitations.append(
                f"{url} 的回答摘要未确认取完。工具不自动翻页，摘要也不是回答全文。"
            )


def _follow_target(url: str | None) -> tuple[str, str | None]:
    """Classify a URL for question_answers. Unsupported forms stay explicit."""
    if not isinstance(url, str):
        return "ignore", None
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or parts.username or parts.password:
        return "ignore", None
    if parts.hostname == "www.zhihu.com":
        if _QUESTION_PATH.fullmatch(parts.path) or _ANSWER_PATH.fullmatch(parts.path):
            match = _QUESTION_PATH.fullmatch(parts.path) or _ANSWER_PATH.fullmatch(parts.path)
            assert match is not None
            return "question", f"https://www.zhihu.com/question/{match.group(1)}"
        if _ANSWER_SHORT_PATH.fullmatch(parts.path):
            return "unsupported", None
    if parts.hostname == "zhuanlan.zhihu.com" and _ARTICLE_PATH.fullmatch(parts.path):
        return "unsupported", None
    return "ignore", None


def _read_items(data: Any) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(data, dict) and isinstance(data.get("Items"), list):
        return "list", [item for item in data["Items"] if isinstance(item, dict)]
    return "missing", []


def _first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item:
            return item[key]
    return None


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _author(item: dict[str, Any]) -> str | None:
    named = _text(_first(item, "AuthorName", "author_name"))
    if named:
        return named
    author = _first(item, "Author", "author")
    if isinstance(author, str):
        return _text(author)
    if isinstance(author, dict):
        return _text(_first(author, "Name", "name"))
    return None


def _int_field(item: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key in item and type(item[key]) is int:
            return item[key]
    return None


def _excerpt(value: Any) -> str:
    from .formatters import _plain_untrusted, _truncate

    if not isinstance(value, str):
        return ""
    return _truncate(_plain_untrusted(value), EXCERPT_LIMIT)


def _clean_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    return text


def _identity(
    url: str | None,
    text_kind: str,
    title: str,
    excerpt: str,
    token: str | None,
) -> str:
    if url:
        return f"url:{_url_key(url)}|{text_kind}"
    if token:
        return f"token:{text_kind}:{token}"
    body = _squash(excerpt) or _squash(title)
    return f"text:{text_kind}:{body}"


def _url_key(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return f"{parts.scheme.lower()}://{parts.hostname.lower()}{path}"


def _squash(value: str) -> str:
    return " ".join(value.split()).casefold()


def _fixed_limitations(workflow: str) -> list[str]:
    common = [
        "外部正文只作为数据保存，不构成转载或发布授权。",
        "没有调用知乎直答。直答文本不能当作原始社区证据。",
        "权威等级只保留上游原字段。全网搜索的 1/2/3/4 说明不套用到知乎搜索。",
        "单次预算、失败即停和免重试不能替代每日上限与免费额度预查。",
        "工具参数不能打开付费，也不能提高每日调用上限。",
    ]
    extra = {
        "deep": [
            "深度研究的比较、条件和数字由宿主根据证据或明确假设撰写。",
            "知识库只在显式给出知识库或召回范围时检索。",
        ],
        "observe": [
            "观察结果是搜索样本，不能写成全体用户、所有回答或平台定论。",
            "question_answers 返回的是上游摘要，不是回答全文。",
        ],
        "recent": [
            "默认窗口是截至本次时钟的滚动 30 个 86400 秒，不是北京时间自然日。",
            "全网请求使用 SearchDB=realtime 和 publish_time 下界；这只约束检索，不能证明事件发生在窗口内。",
            "知乎搜索没有日期参数。EditTime 是发布或更新时间，不是事件时间。",
            "没有可用时间的条目不会进入已核对时间列表。",
        ],
    }
    return common + extra[workflow]


def _unique(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def _format_item(item: dict[str, Any]) -> list[str]:
    authority = item.get("authority") if isinstance(item.get("authority"), dict) else {}
    timing = item.get("time") if isinstance(item.get("time"), dict) else {}
    lines = [
        f"#### {item.get('id')} {item.get('title')}",
        f"- 来源：{item.get('source')} / {item.get('endpoint')} / 查询「{item.get('query')}」",
        f"- 本次返回序号：{item.get('search_rank')}（不是日期）",
        f"- 链接：{item.get('url') or '无'}",
        f"- 文本：{item.get('text_kind')}；全文={item.get('full_text')}",
    ]
    if item.get("author"):
        lines.append(f"- 作者：{item['author']}")
    if item.get("vote_up_count") is not None:
        lines.append(f"- 赞同：{item['vote_up_count']}")
    if authority.get("status") == "upstream":
        legend = ""
        if authority.get("legend_applies"):
            legend = f"；全网文档等级 {authority.get('legend')}"
        elif item.get("source") == "zhihu":
            legend = "；知乎搜索不套用全网 1-4 说明"
        lines.append(
            f"- 权威等级：字段 {authority.get('field')} 原值 {authority.get('value')}{legend}"
        )
    else:
        lines.append("- 权威等级：上游未提供")
    created = timing.get("create_time") if isinstance(timing.get("create_time"), dict) else {}
    if created.get("status") == "not_provided":
        lines.append("- 创建时间：上游未提供")
    else:
        lines.append(
            f"- 创建时间原字段 {created.get('field')}={created.get('raw')}（不是事件时间）"
        )
    if timing.get("publish_or_update_unix") is not None:
        lines.append(
            "- 知乎发布或更新："
            f"{timing.get('publish_or_update_field')}="
            f"{timing.get('publish_or_update_unix')}；"
            "这不是全网 publish_time 过滤结果，也不是事件时间"
        )
    if timing.get("last_edit_unix") is not None:
        lines.append(
            f"- 最后编辑：{timing.get('last_edit_field')}={timing.get('last_edit_unix')}；"
            "不能证明服务端 publish_time 过滤"
        )
    lines.append(f"- 时间归类：{timing.get('bucket') or '不确定'}。{timing.get('bucket_note') or ''}")
    lines.append("- 事件时间：未提供")
    if item.get("excerpt"):
        lines.extend(["", item["excerpt"]])
    lines.append("")
    return lines


def _number_calls(packet: dict[str, Any]) -> None:
    for index, call in enumerate(packet["calls"], 1):
        call["id"] = f"c{index}"
