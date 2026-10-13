import asyncio
import json
from pathlib import Path

import httpx
import pytest
from zhihu_search.call_policy import CallPolicy, CallBlocked, quota_group
from zhihu_search.upstream.http_client import ZhihuRestClient, BASE_URL
from zhihu_search import commands, server, openwebui, cli


def remaining(group="zhihu_search", count=10):
    return [{"APIID": group, "RemainingQuota": count}]


@pytest.mark.asyncio
async def test_defaults_query_each_time_and_share_daily_cap_across_instances(tmp_path):
    requests = []
    async def quota(group):
        requests.append("quota")
        return remaining(group)
    async def execute():
        requests.append("business")
        return "ok"
    policies = [CallPolicy(directory=tmp_path, daily_call_limit=2) for _ in range(4)]
    outcomes = await asyncio.gather(*(p.run("/api/v1/content/zhihu_search", None, quota, execute) for p in policies), return_exceptions=True)
    assert outcomes.count("ok") == 2
    assert sum(isinstance(v, CallBlocked) for v in outcomes) == 2
    assert requests == ["quota", "business", "quota", "business"]
    assert json.loads((tmp_path / "daily.json").read_text())["calls"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], None, {}, remaining(count=0), remaining(count=-1), remaining(count=True), remaining(count="10"), remaining(count=2**63), remaining() * 2])
async def test_unreliable_or_exhausted_quota_never_dispatches(tmp_path, rows):
    async def quota(group): return rows
    async def execute(): pytest.fail("business must not run")
    with pytest.raises(CallBlocked):
        await CallPolicy(directory=tmp_path).run("/api/v1/content/zhihu_search", None, quota, execute)
    assert not (tmp_path / "daily.json").exists()
    assert not (tmp_path / "request.lock").exists()


@pytest.mark.asyncio
async def test_preflight_error_is_closed_without_counting(tmp_path):
    async def quota(group): raise RuntimeError("unavailable")
    async def execute(): pytest.fail("business must not run")
    with pytest.raises(CallBlocked, match="预查失败"):
        await CallPolicy(directory=tmp_path).run("/api/v1/content/zhihu_search", None, quota, execute)
    assert not (tmp_path / "daily.json").exists()


@pytest.mark.asyncio
async def test_paid_is_explicit_still_capped_and_unknown_capability_blocked(tmp_path):
    async def quota(group): pytest.fail("paid mode does not preflight")
    async def execute(): return 1
    policy = CallPolicy(directory=tmp_path, allow_paid=True, daily_call_limit=1)
    assert await policy.run("/api/v1/content/hot_list", None, quota, execute) == 1
    with pytest.raises(CallBlocked, match="每日业务调用上限"):
        await policy.run("/api/v1/content/hot_list", None, quota, execute)
    for path, body in [("/api/v1/user/question_recommendations", None), ("/api/v1/pdf-parse/tasks", {}), ("/v1/chat/completions", {"model": "zhida-thinking-1p5"}), ("/unknown", None)]:
        with pytest.raises(CallBlocked, match="未确认"):
            await policy.run(path, body, quota, execute)


@pytest.mark.asyncio
async def test_cancellation_and_unknown_dispatch_outcome_keep_reservation(tmp_path):
    started = asyncio.Event()
    async def quota(group): return remaining(group, 1)
    async def execute():
        started.set()
        await asyncio.Future()
    policy = CallPolicy(directory=tmp_path)
    task = asyncio.create_task(policy.run("/api/v1/content/zhihu_search", None, quota, execute))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    data = json.loads((tmp_path / "daily.json").read_text())
    assert data["calls"] == 1 and data["uncertain"]["zhihu_search"] == 1
    assert not (tmp_path / "request.lock").exists()
    with pytest.raises(CallBlocked, match="结果未知"):
        await policy.run("/api/v1/content/zhihu_search", None, quota, execute)


@pytest.mark.asyncio
async def test_cancel_waiting_or_preflight_does_not_dispatch_or_reserve(tmp_path):
    (tmp_path / "request.lock").mkdir()
    async def quota(group): pytest.fail("quota must not run")
    async def execute(): pytest.fail("business must not run")
    task = asyncio.create_task(CallPolicy(directory=tmp_path).run("/api/v1/content/hot_list", None, quota, execute))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert (tmp_path / "request.lock").exists()  # Never unlock another owner.
    (tmp_path / "request.lock").rmdir()
    started = asyncio.Event()
    async def delayed_quota(group):
        started.set()
        await asyncio.Future()
    task = asyncio.create_task(CallPolicy(directory=tmp_path).run("/api/v1/content/hot_list", None, delayed_quota, execute))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert not (tmp_path / "daily.json").exists()
    assert not (tmp_path / "request.lock").exists()


@pytest.mark.asyncio
async def test_corrupt_ledger_and_stale_lock_fail_closed(tmp_path):
    async def quota(group): pytest.fail("quota must not run")
    async def execute(): pytest.fail("business must not run")
    (tmp_path / "daily.json").write_text("broken")
    with pytest.raises(CallBlocked, match="记录不可读"):
        await CallPolicy(directory=tmp_path).run("/api/v1/content/hot_list", None, quota, execute)
    (tmp_path / "request.lock").mkdir()
    with pytest.raises(CallBlocked, match="保护锁忙或遗留"):
        await CallPolicy(directory=tmp_path, lock_timeout=0).run("/api/v1/content/hot_list", None, quota, execute)


@pytest.mark.asyncio
async def test_beijing_day_reset_keeps_uncertain_outcomes(tmp_path):
    now = [1791907199.0]  # Immediately before Beijing midnight.
    policy = CallPolicy(directory=tmp_path, allow_paid=True, daily_call_limit=1, now=lambda: now[0])
    async def quota(group): pytest.fail("paid mode")
    async def execute(): return True
    await policy.run("/api/v1/content/hot_list", None, quota, execute)
    now[0] += 2
    await policy.run("/api/v1/content/hot_list", None, quota, execute)
    assert json.loads((tmp_path / "daily.json").read_text())["calls"] == 1


@pytest.mark.parametrize("options", [{"daily_call_limit": 0}, {"daily_call_limit": True}, {"daily_call_limit": 100001}, {"allow_paid": "yes"}])
def test_invalid_configuration_fails_closed(options):
    with pytest.raises(CallBlocked): CallPolicy(**options)


def transport(log, count=10):
    async def handle(request):
        log.append(request.url.path)
        if request.url.path == "/api/v1/quota":
            group = request.url.params.get("APIIDs", "zhihu_search")
            return httpx.Response(200, json={"Code": 0, "Data": remaining(group, count)})
        return httpx.Response(200, json={"Code": 0, "Data": {"Items": []}})
    return httpx.MockTransport(handle)


@pytest.mark.asyncio
async def test_mcp_openapi_and_commands_use_the_same_protected_client(monkeypatch, tmp_path):
    log = []
    async with httpx.AsyncClient(base_url=BASE_URL, transport=transport(log)) as network:
        client = ZhihuRestClient("mock-access-secret", client=network, call_policy=CallPolicy(directory=tmp_path, daily_call_limit=1))
        monkeypatch.setattr(server, "_get_client", lambda: client)
        monkeypatch.setattr(openwebui, "_get_client", lambda: client)
        monkeypatch.setattr(commands, "_make_client", lambda _: (client, False))
        assert (await commands.run_search("普通资料")).success
        assert not (await commands.run_search("普通资料")).success
        # Invoke the real registered MCP callable and FastAPI route.
        result = await server.search("普通资料")
        assert result.is_error
        app = openwebui.create_app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as api:
            response = await api.post("/search", json={"query": "普通资料"})
        assert not response.json()["success"]
        assert log == ["/api/v1/quota", "/api/v1/content/zhihu_search"]
        quota = await client.quota(["question_answers", "question_discovery"])
        assert quota.data[0]["APIID"] == "question_discovery"
        assert log[-1] == "/api/v1/quota"


def test_cli_default_blocks_exhausted_quota_without_business(monkeypatch, tmp_path):
    log = []
    network = httpx.AsyncClient(base_url=BASE_URL, transport=transport(log, 0))
    client = ZhihuRestClient("mock-access-secret", client=network, call_policy=CallPolicy(directory=tmp_path))
    monkeypatch.setattr(commands, "_make_client", lambda _: (client, False))
    try:
        assert cli.main(["search", "普通资料"]) == 1
        assert log == ["/api/v1/quota"]
    finally:
        asyncio.run(network.aclose())


@pytest.mark.asyncio
async def test_upload_chat_and_get_share_request_boundary(tmp_path):
    log = []
    async with httpx.AsyncClient(base_url=BASE_URL, transport=transport(log)) as network:
        client = ZhihuRestClient("mock-access-secret", client=network, call_policy=CallPolicy(directory=tmp_path, daily_call_limit=1))
        await client.hot_list(1)
        with pytest.raises(CallBlocked): await client.knowledge_search("普通资料", recall_scopes=["public"])
        file = tmp_path / "test.txt"
        file.write_text("data")
        with pytest.raises(CallBlocked): await client.upload_knowledge_file(file)
        with pytest.raises(CallBlocked): await client.zhida("普通资料", model="zhida-agent")
        with pytest.raises(CallBlocked): await client.create_pdf_parse_task("file_mock")
        assert log == ["/api/v1/quota", "/api/v1/content/hot_list"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path,body,group", [
    ("/v1/chat/completions", {"model": "zhida-fast-1p5"}, "zhida_openai"),
    ("/v1/chat/completions", {"model": "zhida-thinking-1p5"}, "zhida_openai"),
    ("/api/v1/user/question_recommendations", None, "question_discovery"),
    ("/api/v1/pdf-parse/tasks", {}, "tools"),
    ("/api/v1/ppt-generation/tasks/ppt_mock", None, "tools"),
])
async def test_unpriced_but_mapped_capabilities_work_only_with_verified_free_quota(tmp_path, path, body, group):
    async def quota(value):
        assert value == group
        return remaining(value, 1)
    async def execute(): return "free"
    assert await CallPolicy(directory=tmp_path).run(path, body, quota, execute) == "free"
    with pytest.raises(CallBlocked, match="计费未确认"):
        await CallPolicy(directory=tmp_path, allow_paid=True).run(path, body, quota, execute)


@pytest.mark.asyncio
async def test_unchanged_official_remaining_cannot_be_reused_by_our_clients(tmp_path):
    async def quota(group): return remaining(group, 1)
    async def execute(): return "ok"
    results = await asyncio.gather(*(CallPolicy(directory=tmp_path, daily_call_limit=10).run("/api/v1/content/zhihu_search", None, quota, execute) for _ in range(5)), return_exceptions=True)
    assert results.count("ok") == 1
    assert json.loads((tmp_path / "daily.json").read_text())["free"]["zhihu_search"] == 0
