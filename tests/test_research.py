"""Offline tests for research retrieval and local report rendering."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from zhihu_search import cli, commands, credentials, openwebui, research, server
from zhihu_search.call_policy import CallBlocked
from zhihu_search.research_render import (
    INTERPRETER_JS,
    ReportRejected,
    evaluate,
    format_number,
    parse_formula,
    render_report,
    write_report,
)
from zhihu_search.upstream.http_client import ApiResult


QUESTION = "新房除甲醛空气净化器怎么选"


class FakeClient:
    def __init__(self, *, zhihu=None, web=None, answers=None, knowledge=None, fail=None):
        self.zhihu = zhihu or []
        self.web = web or []
        self.answers = answers or []
        self.knowledge = knowledge or []
        self.fail = fail
        self.calls = []

    async def zhihu_search(self, query, count=10):
        self.calls.append(("zhihu", query, count))
        if self.fail == "zhihu":
            raise CallBlocked("免费额度不足，未发送业务请求。")
        return ApiResult({"Items": self.zhihu, "HasMore": False}, {})

    async def global_search(self, query, count=10, filter="", search_db="all"):
        self.calls.append(("web", query, count, filter, search_db))
        if self.fail == "web":
            raise CallBlocked("已达到本地北京时间每日业务调用上限；额度查询仍可使用。")
        return ApiResult({"Items": self.web, "HasMore": False}, {})

    async def knowledge_search(self, query, *, knowledge_base_ids=None, recall_scopes=None, limit=10):
        self.calls.append(("knowledge", query, tuple(knowledge_base_ids or ()), tuple(recall_scopes or ()), limit))
        return ApiResult({"Items": self.knowledge, "HasMore": False}, {})

    async def question_answers(self, url, *, offset=0, limit=20):
        self.calls.append(("answers", url, offset, limit))
        return ApiResult(
            {"Items": self.answers, "Paging": {"IsEnd": True, "NextOffset": 0}},
            {},
        )

    async def zhida(self, *args, **kwargs):
        raise AssertionError("直答不能当作研究证据")


def _run(**kwargs):
    plan = research.prepare(**kwargs)
    client = kwargs.pop("client")
    return client, plan


async def _collect(client, **kwargs):
    plan = research.prepare(**kwargs)
    return await research.execute(plan, client)


def _item(**overrides):
    item = {
        "id": "e1",
        "source": "zhihu",
        "endpoint": "zhihu_search",
        "query": QUESTION,
        "search_rank": 1,
        "title": "CADR 400 的使用记录",
        "url": "https://www.zhihu.com/question/42/answer/9",
        "author": "甲",
        "vote_up_count": 12,
        "content_type": "answer",
        "excerpt": "这台机器 CADR 400，适合我的卧室。",
        "text_kind": "upstream_excerpt",
        "full_text": False,
        "authority": {
            "status": "upstream",
            "field": "AuthorityLevel",
            "value": "2",
            "legend": None,
            "legend_applies": False,
        },
        "ranking_score": {"status": "not_provided", "value": None},
        "time": {
            "publish_or_update_unix": 1700000000,
            "publish_or_update_field": "EditTime",
            "publish_or_update_role": "publish_or_update",
            "event_unix": None,
            "event_status": "not_provided",
            "in_requested_window": None,
            "bucket": "not_applicable",
        },
        "upstream_times": [],
    }
    item.update(overrides)
    return item


def _packet(items, **overrides):
    packet = {
        "schema": "zhihu-search.evidence.v1",
        "role": "evidence",
        "finished_research": False,
        "workflow": "deep",
        "question": QUESTION,
        "status": "complete",
        "evidence": items,
        "sample": {
            "scope": "search_sample",
            "population_claim": False,
            "note": "这些条目只是本次检索返回的样本，不是知乎全体用户的观点。",
        },
        "chronology": {"confirmed_events": []},
        "dates": {"window_days": None},
        "budget": {"retry": False},
        "limitations": ["外部正文只作为数据保存，不构成转载或发布授权。"],
    }
    packet.update(overrides)
    return packet


def _deep_report():
    return {
        "schema": "zhihu-search.report.v1",
        "workflow": "deep",
        "title": "净化器选择的证据核对",
        "question": QUESTION,
        "status": "complete",
        "incomplete_reason": "",
        "summary": "在已检索到的记录里，CADR 400 被用来描述一台机器。适用面积需要另加假设。",
        "assumptions": [
            {"id": "a_air", "text": "按每小时换气 5 次估计，摘录没有给出换气次数。"},
            {"id": "a_height", "text": "层高按 2.4 米估计，摘录没有给出层高。"},
            {"id": "a_bounds", "text": "滑块范围只用于本地试算，不是上游给出的允许区间。"},
            {"id": "a_model", "text": "适用面积按 CADR 除以换气次数再除以层高估计。"},
        ],
        "conclusions": [
            {
                "id": "k1",
                "text": "摘录只支持 CADR 400 这一台机器的自述，不能外推到所有净化器。",
                "condition": "仅在这条摘录描述的机器上",
                "evidence_ids": ["e1"],
                "assumption_ids": [],
            }
        ],
        "conflicts": [],
        "scenarios": ["卧室、每天运行一段时间的试算"],
        "comparisons": [],
        "disputes": [],
        "mechanisms": [],
        "interactive": {
            "title": "适用面积试算",
            "inputs": [
                {
                    "id": "cadr",
                    "label": "CADR",
                    "value": 400,
                    "min": 200,
                    "max": 600,
                    "step": 10,
                    "unit": "m3/h",
                    "evidence_id": "e1",
                    "value_assumption_id": None,
                    "bounds_assumption_id": "a_bounds",
                },
                {
                    "id": "air_changes",
                    "label": "换气次数",
                    "value": 5,
                    "min": 1,
                    "max": 8,
                    "step": 1,
                    "unit": "次/小时",
                    "evidence_id": None,
                    "value_assumption_id": "a_air",
                    "bounds_assumption_id": "a_bounds",
                },
                {
                    "id": "height",
                    "label": "层高",
                    "value": 2.4,
                    "min": 2,
                    "max": 3,
                    "step": 0.1,
                    "unit": "米",
                    "evidence_id": None,
                    "value_assumption_id": "a_height",
                    "bounds_assumption_id": "a_bounds",
                },
            ],
            "formulas": [
                {
                    "id": "area",
                    "label": "估算适用面积",
                    "expression": "cadr / (air_changes * height)",
                    "unit": "平方米",
                    "assumption_ids": ["a_model"],
                }
            ],
        },
    }


@pytest.mark.asyncio
async def test_deep_packet_keeps_authority_and_does_not_finish_the_report():
    client = FakeClient(
        zhihu=[{
            "Title": "CADR 400 的使用记录",
            "Url": "https://www.zhihu.com/question/42/answer/9",
            "ContentText": "这台机器 CADR 400。",
            "AuthorityLevel": "2",
            "RankingScore": 0.5,
            "EditTime": 1700000000,
            "AuthorName": "甲",
            "VoteUpCount": 3,
        }],
        web=[{
            "Title": "外部页面",
            "Url": "https://example.com/a",
            "ContentText": "另一处说法",
            "AuthorityLevel": "3",
            "RankingScore": 99,
            "PublishTime": 1690000000,
        }],
    )
    packet = await _collect(
        client,
        workflow="deep",
        question=QUESTION,
        follow_questions=False,
        as_of=1700000000,
    )
    assert packet["finished_research"] is False
    assert packet["ask_used"] is False
    assert packet["synthesis"]["html"] is None
    assert packet["synthesis"]["numeric_claims"] == []
    assert packet["chronology"]["confirmed_events"] == []
    zhihu, web = packet["evidence"]
    assert zhihu["authority"]["value"] == "2"
    assert zhihu["authority"]["legend_applies"] is False
    assert zhihu["ranking_score"]["status"] == "upstream"
    assert zhihu["time"]["publish_or_update_role"] == "publish_or_update"
    assert zhihu["time"]["event_status"] == "not_provided"
    assert web["authority"]["legend"] == "high"
    assert web["authority"]["legend_applies"] is True
    assert web["ranking_score"]["status"] == "not_provided"
    assert all(call[0] != "zhida" for call in client.calls)
    text = research.format_evidence_packet(packet)
    assert "不是研究报告" in text
    assert "不套用全网" in text


@pytest.mark.asyncio
async def test_recent_sorts_by_upstream_time_and_drops_undated_from_the_window():
    client = FakeClient(web=[
        {"Title": "较新", "Url": "https://example.com/new", "PublishTime": 1699000000, "ContentText": "新"},
        {"Title": "较早", "Url": "https://example.com/old", "PublishTime": 1698000000, "ContentText": "旧"},
        {"Title": "窗口外", "Url": "https://example.com/out", "PublishTime": 1600000000, "ContentText": "旧闻"},
        {"Title": "无日期", "Url": "https://example.com/none", "ContentText": "没有时间字段"},
    ])
    packet = await _collect(
        client,
        workflow="recent",
        question="减肥药近期进展",
        sources=["web"],
        hosts=["Example.COM"],
        as_of=1700000000,
        window_days=30,
    )
    assert client.calls[0][3] == 'host=="example.com" AND publish_time>=1697408000'
    assert client.calls[0][4] == "realtime"
    chronology = packet["chronology"]
    assert chronology["confirmed_events"] == []
    assert chronology["publish_or_update_in_window"] == ["e2", "e1"]
    assert chronology["publish_or_update_outside_window"] == ["e3"]
    assert chronology["filter_unverified"] == ["e4"]
    assert packet["dates"]["ranking_is_time"] is False
    assert packet["dates"]["zhihu_date_filter"] is False
    assert "e4" not in chronology["publish_or_update_in_window"]


@pytest.mark.asyncio
async def test_observe_follows_question_summary_without_calling_it_a_census():
    client = FakeClient(
        zhihu=[{
            "Title": "谁在赚钱",
            "Url": "https://www.zhihu.com/question/42",
            "ContentText": "一种说法",
            "AuthorName": "乙",
        }],
        answers=[{
            "ContentToken": "ans-7",
            "Url": "https://www.zhihu.com/question/42/answer/7",
            "Summary": "<b>另一种说法</b>",
            "VoteUpCount": 8,
        }],
    )
    packet = await _collect(client, workflow="observe", question="AI 短剧出海谁在赚钱")
    assert [call[0] for call in client.calls] == ["zhihu", "answers"]
    assert client.calls[1][1] == "https://www.zhihu.com/question/42"
    assert client.calls[1][3] == 5
    summary = next(item for item in packet["evidence"] if item["source"] == "question_answers")
    assert summary["text_kind"] == "upstream_summary"
    assert summary["full_text"] is False
    assert summary["author"] is None
    assert summary["vote_up_count"] == 8
    assert "<b>" not in summary["excerpt"]
    assert packet["sample"]["population_claim"] is False
    assert packet["question_traces"][0]["answers_page_complete"] is True


@pytest.mark.asyncio
async def test_budget_stops_without_retry_and_policy_failure_blocks_the_rest():
    client = FakeClient(fail="zhihu", web=[{"Title": "不该发送", "Url": "https://example.com/x"}])
    packet = await _collect(
        client,
        workflow="deep",
        question=QUESTION,
        follow_questions=False,
        max_calls=4,
    )
    assert [call[0] for call in client.calls] == ["zhihu"]
    assert packet["status"] == "blocked"
    assert packet["budget"]["retry"] is False
    assert packet["budget"]["stop_reason"] == "call_policy"
    assert packet["calls"][1]["status"] == "not_sent"

    limited = FakeClient(zhihu=[{"Title": "一条", "Url": "https://example.com/only"}])
    packet = await _collect(
        limited,
        workflow="deep",
        question=QUESTION,
        follow_questions=False,
        max_calls=1,
    )
    assert [call[0] for call in limited.calls] == ["zhihu"]
    assert packet["status"] == "partial"
    assert packet["budget"]["stop_reason"] == "budget"
    assert packet["calls"][1]["status"] == "not_sent"


@pytest.mark.asyncio
async def test_invalid_plan_does_not_load_credentials_or_search(monkeypatch):
    def boom():
        raise AssertionError("不应该读取凭证")

    monkeypatch.setattr(credentials, "load", boom)
    result = await commands.run_research(workflow="deep", question="超" * 101)
    assert result.success is False
    assert "angle" in (result.error or "")
    with pytest.raises(research.InvalidArguments):
        research.prepare(workflow="deep", question=QUESTION, sources=["vector"])
    with pytest.raises(research.InvalidArguments):
        research.prepare(workflow="deep", question=QUESTION, sources=["knowledge"])
    with pytest.raises(research.InvalidArguments):
        research.prepare(workflow="recent", question="减肥药近期进展", hosts=["www.zhihu.com"])


@pytest.mark.asyncio
async def test_knowledge_search_uses_only_the_given_base():
    client = FakeClient(knowledge=[{
        "DocName": "内部笔记",
        "RecallContentID": "recall-1",
        "Content": ["CADR 400 的内部记录"],
        "OriginUrl": "https://example.com/note",
    }])
    packet = await _collect(
        client,
        workflow="deep",
        question=QUESTION,
        sources=["knowledge"],
        knowledge_base_ids=["kb_1"],
        follow_questions=False,
    )
    assert client.calls == [("knowledge", QUESTION, ("kb_1",), (), 5)]
    assert packet["evidence"][0]["text_kind"] == "knowledge_snippet"
    assert packet["evidence"][0]["authority"]["status"] == "not_provided"


@pytest.mark.asyncio
async def test_duplicates_collapse_and_bad_urls_are_dropped():
    client = FakeClient(zhihu=[
        {"Title": "同一篇", "Url": "https://example.com/a/", "ContentText": "甲"},
        {"Title": "同一篇", "Url": "https://example.com/a", "ContentText": "乙"},
        {"Title": "坏链接", "Url": "javascript:alert(1)", "ContentText": "丙"},
    ])
    packet = await _collect(
        client,
        workflow="observe",
        question="同一篇资料怎么看",
        sources=["zhihu"],
        follow_questions=False,
    )
    urls = [item["url"] for item in packet["evidence"]]
    assert urls == ["https://example.com/a/", None]
    assert packet["duplicates"][0]["kept_id"] == "e1"


def test_formula_rejects_literals_and_matches_javascript():
    ast = parse_formula("cadr / (air_changes * height)", {"cadr", "air_changes", "height"})
    value = evaluate(ast, {"cadr": 400, "air_changes": 5, "height": 2.4})
    assert format_number(value) == "33.333333"
    from zhihu_search.research_render import FormulaError
    with pytest.raises(FormulaError, match="数字字面量"):
        parse_formula("cadr / 5", {"cadr"})
    if shutil.which("node"):
        script = (
            INTERPRETER_JS
            + "\nconst ast = "
            + json.dumps(ast)
            + ";\nprocess.stdout.write(formatNum(evalAst(ast, {cadr: 400, air_changes: 5, height: 2.4})));"
        )
        completed = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
        assert completed.stdout == "33.333333"


def test_render_writes_sourced_calculation_and_escapes_html(tmp_path):
    evidence = _item(excerpt='这台机器 CADR 400。<script>alert(1)</script>')
    rendered = write_report(_packet([evidence]), _deep_report(), tmp_path)
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert rendered["data"]["publishable"] is False
    assert data["finished_research"] is True
    assert data["network_assets"] is False
    assert "33.333333" in html
    assert "33.333333" in markdown
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert(1)" in html
    assert " src=" not in html
    assert "@import" not in html
    assert "default-src 'none'" in html
    assert "eval(" not in html
    assert "innerHTML" not in html
    assert html.count("<script") == 2
    assert "https://www.zhihu.com/question/42/answer/9" in html
    assert "不套用" in markdown or "权威等级原值：2" in markdown


def test_render_rejects_unsourced_numbers_population_claims_and_empty_packets(tmp_path):
    packet = _packet([_item()])
    report = _deep_report()
    report["interactive"]["inputs"][0]["value"] = 500
    with pytest.raises(ReportRejected, match="没有出现在证据"):
        render_report(packet, report)
    report = _deep_report()
    report["summary"] = "全体用户都应该买这台机器。"
    with pytest.raises(ReportRejected, match="全体用户"):
        render_report(packet, report)
    report = _deep_report()
    report["interactive"]["formulas"][0]["expression"] = "cadr / 5"
    with pytest.raises(ReportRejected, match="数字字面量"):
        render_report(packet, report)
    with pytest.raises(ReportRejected, match="没有证据"):
        render_report(_packet([]), _deep_report())
    partial = _packet([_item()], status="partial")
    report = _deep_report()
    with pytest.raises(ReportRejected, match="不能是 complete"):
        render_report(partial, report)
    assert not (tmp_path / "report.html").exists()


def test_observe_report_lists_viewpoints_and_does_not_invent_authors():
    first = _item(id="e1", author="甲", excerpt="平台分成较高。", title="说法甲")
    second = _item(
        id="e2",
        author=None,
        vote_up_count=None,
        excerpt="制作方才是收入主体。",
        title="说法乙",
        url="https://www.zhihu.com/question/42/answer/10",
    )
    packet = _packet(
        [first, second],
        workflow="observe",
        question="AI 短剧出海谁在赚钱",
    )
    report = {
        "schema": "zhihu-search.report.v1",
        "workflow": "observe",
        "title": "短剧出海的两种说法",
        "question": "AI 短剧出海谁在赚钱",
        "status": "complete",
        "incomplete_reason": "",
        "summary": "本次样本里有两种收入归属说法。",
        "assumptions": [],
        "conclusions": [],
        "conflicts": [],
        "viewpoints": [
            {"id": "v1", "text": "一种说法认为平台分成较高。", "evidence_ids": ["e1"]},
            {"id": "v2", "text": "另一种说法认为制作方才是收入主体。", "evidence_ids": ["e2"]},
        ],
        "progress": [{"id": "p1", "text": "公开摘录仍停留在商业模式争论。", "evidence_ids": ["e1"]}],
        "open_questions": [{"id": "q1", "text": "样本没有给出可核对的分成合同。", "evidence_ids": []}],
    }
    rendered = render_report(packet, report)
    assert "并列观点" in rendered["markdown"]
    assert "不是知乎全体用户" in rendered["html"]
    assert "作者：甲" in rendered["markdown"]
    assert "作者：乙" not in rendered["markdown"]
    assert "制作方才是收入主体" in rendered["html"]


def test_recent_report_separates_event_dates_from_publication_dates():
    dated = _item(
        id="e1",
        title="11 月进展",
        excerpt="2026-11-01 公布了新的试验数据。",
        url="https://example.com/glp",
        source="web",
        time={
            "publish_or_update_unix": 1761955200,
            "publish_or_update_field": "PublishTime",
            "publish_or_update_role": "upstream_publish_time",
            "event_unix": None,
            "event_status": "not_provided",
            "in_requested_window": True,
            "bucket": "verified_in_window",
        },
    )
    undated = _item(
        id="e2",
        title="没有日期的转述",
        excerpt="有人提到后续会议，但没有写日期。",
        url="https://example.com/rumor",
        author=None,
        vote_up_count=None,
    )
    packet = _packet(
        [dated, undated],
        workflow="recent",
        question="减肥药近期进展",
        dates={"window_days": 30},
    )
    report = {
        "schema": "zhihu-search.report.v1",
        "workflow": "recent",
        "title": "减肥药近 30 天",
        "question": "减肥药近期进展",
        "status": "complete",
        "incomplete_reason": "",
        "summary": "只有一条摘录写明了事件日期，另一条日期不确定。",
        "assumptions": [],
        "conclusions": [],
        "conflicts": [],
        "window_days": 30,
        "changes": [
            {"id": "c_new", "text": "摘录写到 2026-11-01 的试验数据。", "kind": "new", "evidence_ids": ["e1"]},
            {"id": "c_impact", "text": "没有日期的转述不能算作新事件。", "kind": "impact", "evidence_ids": ["e2"]},
        ],
        "timeline": [
            {
                "id": "t1",
                "title": "试验数据公布",
                "uncertain": False,
                "event_date": "2026-11-01",
                "event_date_basis": "excerpt",
                "assumption_id": None,
                "evidence_ids": ["e1"],
                "impact": "这是摘录里的事件日期。",
                "merge_key": None,
            },
            {
                "id": "t2",
                "title": "后续会议",
                "uncertain": True,
                "event_date": None,
                "event_date_basis": None,
                "assumption_id": None,
                "evidence_ids": ["e2"],
                "impact": "日期不确定，不进入确认时间线。",
                "merge_key": None,
            },
        ],
        "next_checks": ["核对原始公告是否还有更精确的时间"],
    }
    rendered = render_report(packet, report)
    assert "确认的事件时间" in rendered["markdown"]
    assert "2026-11-01 试验数据公布" in rendered["markdown"]
    assert "日期不确定" in rendered["markdown"]
    assert "不是事件日期" in rendered["markdown"]
    confirmed = rendered["html"].split("日期不确定")[0]
    assert "后续会议" not in confirmed
    invented = json.loads(json.dumps(report))
    invented["timeline"][0]["event_date"] = "2026-11-02"
    with pytest.raises(ReportRejected, match="没有出现在所引证据"):
        render_report(packet, invented)


def test_cli_render_and_schema_do_not_expose_payment_controls(tmp_path):
    evidence = tmp_path / "evidence.json"
    synthesis = tmp_path / "synthesis.json"
    out = tmp_path / "out"
    evidence.write_text(json.dumps(_packet([_item()])), encoding="utf-8")
    synthesis.write_text(json.dumps(_deep_report()), encoding="utf-8")
    assert cli.main(["research-render", str(evidence), str(synthesis), "--out", str(out)]) == 0
    assert (out / "report.html").is_file()
    parser = cli._build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    for name in ("research", "research-render"):
        dests = {action.dest for action in subparsers.choices[name]._actions}
        assert "allow_paid" not in dests
        assert "daily_call_limit" not in dests
    schema = openwebui.create_app(api_key=None).openapi()
    research_props = schema["components"]["schemas"]["ResearchRequest"]["properties"]
    render_props = schema["components"]["schemas"]["ResearchRenderRequest"]["properties"]
    assert "allow_paid" not in research_props
    assert "daily_call_limit" not in research_props
    assert set(render_props) == {"evidence", "report"}
    rejected = schema["paths"]["/research/render"]["post"]
    assert rejected["operationId"] == "research_render"


@pytest.mark.asyncio
async def test_mcp_research_tools_keep_payment_fields_out_of_the_schema():
    server.configure_mcp_tools("full")
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    assert {"research", "research_render"} <= set(tools)
    for name in ("research", "research_render"):
        properties = tools[name].parameters["properties"]
        assert "allow_paid" not in properties
        assert "daily_call_limit" not in properties
        assert "access_secret" not in properties
    assert tools["search"].parameters["properties"]["scope"]["enum"] == ["zhihu", "web"]
