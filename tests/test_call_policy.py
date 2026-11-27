import asyncio
import hashlib
import json
import os
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from zhihu_search.call_policy import CallPolicy, CallBlocked, quota_group
from zhihu_search.upstream.http_client import ZhihuRestClient, ZhihuResponseCache, BASE_URL
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
    assert requests.count("quota") == 2
    assert requests.count("business") == 2
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
    with pytest.raises(CallBlocked, match="保护锁忙"):
        await CallPolicy(directory=tmp_path, lock_timeout=0).run("/api/v1/content/hot_list", None, quota, execute)


@pytest.mark.asyncio
async def test_beijing_day_reset_clears_uncertain_checked_free_and_calls(tmp_path):
    now = [1791907199.0]  # Immediately before Beijing midnight.
    policy = CallPolicy(directory=tmp_path, allow_paid=True, daily_call_limit=1, now=lambda: now[0])
    async def quota(group): pytest.fail("paid mode")
    async def execute(): return True
    await policy.run("/api/v1/content/hot_list", None, quota, execute)
    ledger = json.loads((tmp_path / "daily.json").read_text())
    ledger["uncertain"] = {"zhihu_search": 4}
    ledger["free"] = {"zhihu_search": 30}
    ledger["checked"] = {"zhihu_search": int(now[0])}
    ledger["futureUnknown"] = {"kept": True}
    (tmp_path / "daily.json").write_text(json.dumps(ledger))
    now[0] += 2
    await policy.run("/api/v1/content/hot_list", None, quota, execute)
    data = json.loads((tmp_path / "daily.json").read_text())
    assert data["calls"] == 1
    assert "zhihu_search" not in data["uncertain"]
    assert data["free"] == {}
    assert data["checked"] == {}
    assert data["futureUnknown"] == {"kept": True}


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
        assert not (await commands.run_search("另一份资料")).success
        # Invoke the real registered MCP callable and FastAPI route.
        result = await server.search("服务资料")
        assert result.is_error
        app = openwebui.create_app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as api:
            response = await api.post("/search", json={"query": "开放资料"})
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
async def test_research_recent_uses_realtime_filter_under_the_same_policy(tmp_path):
    seen = []

    async def handle(request):
        seen.append((request.url.path, dict(request.url.params)))
        if request.url.path == "/api/v1/quota":
            group = request.url.params.get("APIIDs", "global_search")
            return httpx.Response(200, json={"Code": 0, "Data": [{"APIID": group, "RemainingQuota": 5}]})
        return httpx.Response(200, json={"Code": 0, "Data": {"Items": [], "HasMore": False}})

    async with httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handle)) as network:
        client = ZhihuRestClient(
            "mock-access-secret",
            client=network,
            call_policy=CallPolicy(directory=tmp_path, daily_call_limit=1),
        )
        result = await commands.run_research(
            workflow="recent",
            question="减肥药近期进展",
            sources=["web"],
            hosts=["example.com"],
            max_calls=1,
            window_days=30,
            as_of=1700000000,
            follow_questions=False,
            client=client,
        )
        blocked = await commands.run_research(
            workflow="recent",
            question="减肥药再次检索",
            sources=["web"],
            max_calls=1,
            as_of=1700000000,
            follow_questions=False,
            client=client,
        )
    assert result.success and result.data["calls"][0]["status"] == "ok"
    assert seen[0][0] == "/api/v1/quota"
    assert seen[1][0] == "/api/v1/content/global_search"
    assert seen[1][1]["SearchDB"] == "realtime"
    assert seen[1][1]["Filter"] == 'host=="example.com" AND publish_time>=1697408000'
    assert blocked.success and blocked.data["calls"][0]["status"] == "error"
    assert blocked.data["budget"]["stop_reason"] == "call_policy"
    assert [path for path, _ in seen].count("/api/v1/content/global_search") == 1


@pytest.mark.asyncio
async def test_unchanged_official_remaining_cannot_be_reused_by_our_clients(tmp_path):
    async def quota(group): return remaining(group, 1)
    async def execute(): return "ok"
    results = await asyncio.gather(*(CallPolicy(directory=tmp_path, daily_call_limit=10).run("/api/v1/content/zhihu_search", None, quota, execute) for _ in range(5)), return_exceptions=True)
    assert results.count("ok") == 1
    assert json.loads((tmp_path / "daily.json").read_text())["free"]["zhihu_search"] == 0


@pytest.mark.asyncio
async def test_concurrent_requests_overlap_in_execute(tmp_path):
    first_inside = asyncio.Event()
    second_inside = asyncio.Event()

    async def quota(group): return remaining(group, 10)
    async def execute_first():
        first_inside.set()
        await asyncio.wait_for(second_inside.wait(), 1)
        return "first"
    async def execute_second():
        second_inside.set()
        await asyncio.wait_for(first_inside.wait(), 1)
        return "second"

    policy = CallPolicy(directory=tmp_path)
    results = await asyncio.wait_for(asyncio.gather(
        policy.run("/api/v1/content/zhihu_search", None, quota, execute_first),
        policy.run("/api/v1/content/zhihu_search", None, quota, execute_second),
    ), 2)
    assert sorted(results) == ["first", "second"]


@pytest.mark.asyncio
async def test_quota_check_cache_refreshes_after_ttl_and_low_floor_checks_every_time(tmp_path):
    now = [1767225600.0]
    checks = 0
    async def quota(group):
        nonlocal checks
        checks += 1
        return remaining(group, 100)
    async def execute(): return "ok"
    policy = CallPolicy(directory=tmp_path, now=lambda: now[0])
    await policy.run("/api/v1/content/zhihu_search", None, quota, execute)
    await policy.run("/api/v1/content/zhihu_search", None, quota, execute)
    assert checks == 1
    now[0] += 301
    await policy.run("/api/v1/content/zhihu_search", None, quota, execute)
    assert checks == 2

    low_dir = tmp_path / "low"
    low_checks = 0
    async def low_quota(group):
        nonlocal low_checks
        low_checks += 1
        return remaining(group, 19)
    low_policy = CallPolicy(directory=low_dir, now=lambda: now[0])
    await low_policy.run("/api/v1/content/zhihu_search", None, low_quota, execute)
    await low_policy.run("/api/v1/content/zhihu_search", None, low_quota, execute)
    assert low_checks == 2


@pytest.mark.asyncio
async def test_stale_lock_is_reclaimed_and_fresh_lock_reports_automatic_recovery(tmp_path):
    lock = tmp_path / "request.lock"
    lock.mkdir()
    old = time.time() - 120
    os.utime(lock, (old, old))
    async def quota(group): return remaining(group, 10)
    async def execute(): return "ok"
    assert await CallPolicy(directory=tmp_path).run("/api/v1/content/zhihu_search", None, quota, execute) == "ok"
    assert not lock.exists()
    assert not (tmp_path / "request.lock.owner.json").exists()

    lock.mkdir()
    with pytest.raises(CallBlocked, match="60 秒后自动恢复"):
        await CallPolicy(directory=tmp_path, lock_timeout=0).run("/api/v1/content/zhihu_search", None, quota, execute)
    lock.rmdir()


@pytest.mark.asyncio
async def test_release_never_removes_lock_with_a_different_owner_token(tmp_path):
    lock = tmp_path / "request.lock"
    owner = tmp_path / "request.lock.owner.json"
    lock.mkdir()
    owner.write_text(json.dumps({"token": "actual", "pid": 123, "acquiredAt": int(time.time() * 1000)}))
    policy = CallPolicy(directory=tmp_path)
    await policy._release("different")
    assert lock.exists() and owner.exists()
    await policy._release("actual")
    assert not lock.exists() and not owner.exists()


@pytest.mark.asyncio
async def test_cross_language_checked_ledger_uses_cache_and_settles_reservation(tmp_path):
    today = datetime.fromtimestamp(time.time(), timezone(timedelta(hours=8))).date().isoformat()
    now_s = int(time.time())
    row = {"version": 1, "day": today, "calls": 3, "uncertain": {"zhihu_search": 1}, "free": {"zhihu_search": 50}, "checked": {"zhihu_search": now_s - 10}}
    (tmp_path / "daily.json").write_text(json.dumps(row, separators=(",", ":")))

    async def quota(group): pytest.fail("cached quota check must not run")
    async def execute(): return "ok"
    assert await CallPolicy(directory=tmp_path).run("/api/v1/content/zhihu_search", None, quota, execute) == "ok"
    data = json.loads((tmp_path / "daily.json").read_text())
    assert data["free"]["zhihu_search"] == 49
    assert data["uncertain"]["zhihu_search"] == 1
    assert data["calls"] == 4
    assert data["checked"]["zhihu_search"] == now_s - 10


@pytest.mark.asyncio
async def test_phase2_lock_failure_does_not_fail_successful_call(tmp_path):
    async def quota(group): return remaining(group, 10)
    async def execute():
        (tmp_path / "request.lock").mkdir()
        return "ok"
    result = await CallPolicy(directory=tmp_path, lock_timeout=0).run("/api/v1/content/zhihu_search", None, quota, execute)
    assert result == "ok"
    assert json.loads((tmp_path / "daily.json").read_text())["uncertain"]["zhihu_search"] == 1
    (tmp_path / "request.lock").rmdir()


def test_default_daily_cap_is_1000(monkeypatch):
    monkeypatch.delenv("ZHIHU_DAILY_CALL_LIMIT", raising=False)
    assert CallPolicy().daily_call_limit == 1000


@pytest.mark.asyncio
async def test_invalid_checked_record_fails_closed(tmp_path):
    today = datetime.fromtimestamp(time.time(), timezone(timedelta(hours=8))).date().isoformat()
    (tmp_path / "daily.json").write_text(json.dumps({"version": 1, "day": today, "calls": 0, "uncertain": {}, "free": {}, "checked": {"zhihu_search": -1}}))
    async def quota(group): pytest.fail("quota must not run")
    async def execute(): pytest.fail("business must not run")
    with pytest.raises(CallBlocked, match="预查记录无效"):
        await CallPolicy(directory=tmp_path).run("/api/v1/content/zhihu_search", None, quota, execute)


def search_transport(log, fail_first=False):
    attempts = {"count": 0}
    async def handle(request):
        log.append((request.url.path, dict(request.url.params)))
        if request.url.path == "/api/v1/content/zhihu_search":
            attempts["count"] += 1
            if fail_first and attempts["count"] == 1:
                return httpx.Response(500, json={"Code": 90001, "Message": "upstream", "Data": {}})
        return httpx.Response(200, json={"Code": 0, "Data": {"Items": [{"Title": "条目"}], "HasMore": False}})
    return httpx.MockTransport(handle)


@pytest.mark.asyncio
async def test_response_cache_reuses_gets_by_params_secret_and_ttl(tmp_path):
    log = []
    now = [1000.0]
    cache = ZhihuResponseCache(now=lambda: now[0])
    async with httpx.AsyncClient(base_url=BASE_URL, transport=search_transport(log)) as network:
        policy = CallPolicy(directory=tmp_path, allow_paid=True)
        first = ZhihuRestClient("secret-one", client=network, call_policy=policy, response_cache=cache)
        second = ZhihuRestClient("secret-two", client=network, call_policy=policy, response_cache=cache)
        initial = await first.zhihu_search("RAG")
        initial.data["Items"].append({"Title": "调用方修改"})
        cached = await first.zhihu_search("RAG")
        assert [item["Title"] for item in cached.data["Items"]] == ["条目"]
        await first.zhihu_search("RAG", count=6)
        await second.zhihu_search("RAG")
        now[0] += 601
        await first.zhihu_search("RAG")
    business = [entry for entry in log if entry[0] == "/api/v1/content/zhihu_search"]
    assert len(business) == 4
    assert json.loads((tmp_path / "daily.json").read_text())["calls"] == 4


@pytest.mark.asyncio
async def test_response_cache_never_caches_errors(tmp_path):
    log = []
    async with httpx.AsyncClient(base_url=BASE_URL, transport=search_transport(log, fail_first=True)) as network:
        client = ZhihuRestClient("secret-one", client=network, call_policy=CallPolicy(directory=tmp_path, allow_paid=True))
        with pytest.raises(Exception):
            await client.zhihu_search("RAG")
        assert (await client.zhihu_search("RAG")).data["Items"][0]["Title"] == "条目"
    assert [entry for entry in log if entry[0] == "/api/v1/content/zhihu_search"].__len__() == 2


@pytest.mark.asyncio
async def test_credential_isolation_resets_cache_and_floor_while_none_omits_key(tmp_path):
    now = [1767225600.0]
    quotas = {"secret-a": 100, "secret-b": 0, "secret-c": 50}
    quota_calls = []

    def make_transport(secret_label):
        async def handle(request):
            if request.url.path == "/api/v1/quota":
                quota_calls.append(secret_label)
                group = request.url.params.get("APIIDs", "zhihu_search")
                return httpx.Response(200, json={"Code": 0, "Data": remaining(group, quotas[secret_label])})
            return httpx.Response(200, json={"Code": 0, "Data": {"Items": [], "HasMore": False}})
        return httpx.MockTransport(handle)

    # 1. Default credential=None must not write "credential" into daily.json.
    plain_dir = tmp_path / "plain"
    async def plain_quota(group): return remaining(group, 10)
    async def plain_exec(): return "ok"
    assert await CallPolicy(directory=plain_dir, now=lambda: now[0]).run("/api/v1/content/zhihu_search", None, plain_quota, plain_exec) == "ok"
    assert "credential" not in json.loads((plain_dir / "daily.json").read_text(encoding="utf-8"))

    # 2. Switching from high-quota account A to exhausted account B within 5 min forces immediate quota check.
    shared_dir = tmp_path / "shared"
    policy = CallPolicy(directory=shared_dir, now=lambda: now[0])
    async with httpx.AsyncClient(base_url=BASE_URL, transport=make_transport("secret-a")) as net_a:
        client_a = ZhihuRestClient("secret-a", client=net_a, call_policy=policy)
        await client_a.zhihu_search("第一次")
        await client_a.zhihu_search("第二次")
    assert quota_calls == ["secret-a"]
    ledger_a = json.loads((shared_dir / "daily.json").read_text(encoding="utf-8"))
    assert ledger_a["free"]["zhihu_search"] == 98
    assert ledger_a["credential"] == hashlib.sha256(b"secret-a").hexdigest()[:16]

    async with httpx.AsyncClient(base_url=BASE_URL, transport=make_transport("secret-b")) as net_b:
        client_b = ZhihuRestClient("secret-b", client=net_b, call_policy=policy)
        with pytest.raises(CallBlocked, match="免费额度不足"):
            await client_b.zhihu_search("切到零额度账号")
    assert quota_calls == ["secret-a", "secret-b"]

    # 3. Switching from free=0 exhausted account A to funded account C unlocks immediately without waiting for midnight.
    quotas["secret-a"] = 1
    exhausted_dir = tmp_path / "exhausted"
    policy_ex = CallPolicy(directory=exhausted_dir, now=lambda: now[0])
    async with httpx.AsyncClient(base_url=BASE_URL, transport=make_transport("secret-a")) as net_a2:
        client_a2 = ZhihuRestClient("secret-a", client=net_a2, call_policy=policy_ex)
        await client_a2.zhihu_search("耗尽最后一格")
        assert json.loads((exhausted_dir / "daily.json").read_text(encoding="utf-8"))["free"]["zhihu_search"] == 0
        with pytest.raises(CallBlocked, match="免费额度不足"):
            await client_a2.zhihu_search("同账号被拦")

    async with httpx.AsyncClient(base_url=BASE_URL, transport=make_transport("secret-c")) as net_c:
        client_c = ZhihuRestClient("secret-c", client=net_c, call_policy=policy_ex)
        await client_c.zhihu_search("新账号立即恢复")
    ledger_c = json.loads((exhausted_dir / "daily.json").read_text(encoding="utf-8"))
    assert ledger_c["credential"] == hashlib.sha256(b"secret-c").hexdigest()[:16]
    assert ledger_c["free"]["zhihu_search"] == 49
    assert ledger_c["uncertain"].get("zhihu_search", 0) == 0


@pytest.mark.asyncio
async def test_concurrent_inflight_quota_refresh_does_not_double_deduct_free_floor(tmp_path):
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    upstream_remaining = [10]

    async def quota(group):
        return remaining(group, upstream_remaining[0])

    async def execute_first():
        # Upstream has already deducted request A before request B refreshes quota.
        upstream_remaining[0] = 9
        first_entered.set()
        await release_first.wait()
        return "first"

    async def execute_second():
        upstream_remaining[0] = 8
        return "second"

    policy = CallPolicy(directory=tmp_path)
    task_a = asyncio.create_task(policy.run("/api/v1/content/zhihu_search", None, quota, execute_first))
    await first_entered.wait()
    assert await policy.run("/api/v1/content/zhihu_search", None, quota, execute_second) == "second"
    release_first.set()
    assert await task_a == "first"

    data = json.loads((tmp_path / "daily.json").read_text(encoding="utf-8"))
    assert data["calls"] == 2
    assert data["uncertain"]["zhihu_search"] == 0
    assert data["free"]["zhihu_search"] == 8


@pytest.mark.asyncio
async def test_execute_oserror_propagates_while_reserve_oserror_maps_to_call_blocked(tmp_path):
    async def quota(group):
        return remaining(group, 5)

    async def broken_network():
        raise ssl.SSLError(1, "tlsv1 alert internal error")

    policy = CallPolicy(directory=tmp_path)
    with pytest.raises(ssl.SSLError):
        await policy.run("/api/v1/content/zhihu_search", None, quota, broken_network)

    bad_file_dir = tmp_path / "not_a_dir"
    bad_file_dir.write_text("occupied", encoding="utf-8")
    with pytest.raises(CallBlocked, match="本地保护存储不可用"):
        await CallPolicy(directory=bad_file_dir).run("/api/v1/content/zhihu_search", None, quota, broken_network)


@pytest.mark.asyncio
async def test_stale_lock_with_owner_uses_injected_clock_and_release_respects_reclaim_mutex(tmp_path):
    now = [1_700_000_000.0]
    policy = CallPolicy(directory=tmp_path, lock_timeout=0, now=lambda: now[0])
    token = await policy._acquire()
    assert (tmp_path / "request.lock").exists()
    assert (tmp_path / "request.lock.owner.json").exists()

    # Future acquiredAt skew is clamped to now + 0.05 rather than producing huge negative age.
    (tmp_path / "request.lock.owner.json").write_text(
        json.dumps({"token": token, "pid": 123, "acquiredAt": int((now[0] + 3600) * 1000)}),
        encoding="utf-8",
    )
    age_clamped = policy._lock_age()
    assert age_clamped is not None and -0.06 <= age_clamped <= 0.0
    (tmp_path / "request.lock.owner.json").write_text(
        json.dumps({"token": token, "pid": 123, "acquiredAt": int(now[0] * 1000)}),
        encoding="utf-8",
    )

    now[0] += 30
    async def quota(group): return remaining(group, 10)
    async def execute(): return "ok"
    with pytest.raises(CallBlocked, match="60 秒后自动恢复"):
        await CallPolicy(directory=tmp_path, lock_timeout=0, now=lambda: now[0]).run(
            "/api/v1/content/zhihu_search", None, quota, execute
        )

    # Advance injected clock past 60s without touching filesystem mtime via os.utime.
    now[0] += 31
    assert await CallPolicy(directory=tmp_path, lock_timeout=0, now=lambda: now[0]).run(
        "/api/v1/content/zhihu_search", None, quota, execute
    ) == "ok"

    # Simulate old owner waking up in _release while reclaim mutex is held during successor takeover.
    successor_token = await policy._acquire()
    reclaim_dir = tmp_path / "request.lock.reclaim"
    reclaim_dir.mkdir()

    def replace_under_reclaim():
        time.sleep(0.03)
        (tmp_path / "request.lock.owner.json").write_text(
            json.dumps({"token": "new-successor", "pid": 999, "acquiredAt": int(now[0] * 1000)}),
            encoding="utf-8",
        )
        reclaim_dir.rmdir()

    worker = threading.Thread(target=replace_under_reclaim)
    worker.start()
    await policy._release(successor_token)
    worker.join()
    assert (tmp_path / "request.lock").exists()
    assert json.loads((tmp_path / "request.lock.owner.json").read_text(encoding="utf-8"))["token"] == "new-successor"
    await policy._release("new-successor")
    assert not (tmp_path / "request.lock").exists()


def test_response_cache_enforces_200_entry_lru_eviction():
    from zhihu_search.upstream.http_client import ApiResult

    now = [1000.0]
    cache = ZhihuResponseCache(now=lambda: now[0])
    for idx in range(200):
        cache.set(f"key-{idx}", ApiResult(data={"idx": idx}, headers={}), 600.0)
    # Touch key-0 so key-1 becomes the least-recently-used entry.
    assert cache.get("key-0").data["idx"] == 0
    cache.set("key-200", ApiResult(data={"idx": 200}, headers={}), 600.0)
    assert cache.get("key-1") is None
    assert cache.get("key-0").data["idx"] == 0
    assert cache.get("key-200").data["idx"] == 200


@pytest.mark.asyncio
async def test_settle_skips_decrement_across_credential_switch_and_day_rollover(tmp_path):
    # 1. Credential switch while Request A is in-flight must not erase Account B's uncertain reservation.
    cred_dir = tmp_path / "cred_switch"
    entered_a = asyncio.Event()
    release_a = asyncio.Event()
    entered_b = asyncio.Event()

    async def quota(group):
        return remaining(group, 10)

    async def exec_a():
        entered_a.set()
        await release_a.wait()
        return "ok-a"

    async def exec_b_hang():
        entered_b.set()
        await asyncio.Future()

    policy = CallPolicy(directory=cred_dir)
    task_a = asyncio.create_task(
        policy.run("/api/v1/content/zhihu_search", None, quota, exec_a, credential="cred-account-a")
    )
    await entered_a.wait()

    task_b = asyncio.create_task(
        policy.run("/api/v1/content/zhihu_search", None, quota, exec_b_hang, credential="cred-account-b")
    )
    await entered_b.wait()
    task_b.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task_b

    release_a.set()
    assert await task_a == "ok-a"
    ledger = json.loads((cred_dir / "daily.json").read_text(encoding="utf-8"))
    assert ledger["credential"] == "cred-account-b"
    assert ledger["uncertain"]["zhihu_search"] == 1

    # 2. Beijing midnight rollover while Request A is in-flight must not decrement new day's uncertain count.
    day_dir = tmp_path / "day_rollover"
    now = [1791907199.0]  # 1s before Beijing midnight
    day_entered_a = asyncio.Event()
    day_release_a = asyncio.Event()
    day_entered_b = asyncio.Event()

    async def day_exec_a():
        day_entered_a.set()
        await day_release_a.wait()
        return "ok-day-a"

    async def day_exec_b_hang():
        day_entered_b.set()
        await asyncio.Future()

    day_policy = CallPolicy(directory=day_dir, now=lambda: now[0])
    day_task_a = asyncio.create_task(
        day_policy.run("/api/v1/content/zhihu_search", None, quota, day_exec_a, credential="cred-same")
    )
    await day_entered_a.wait()

    now[0] += 2  # Cross Beijing midnight
    day_task_b = asyncio.create_task(
        day_policy.run("/api/v1/content/zhihu_search", None, quota, day_exec_b_hang, credential="cred-same")
    )
    await day_entered_b.wait()
    day_task_b.cancel()
    with pytest.raises(asyncio.CancelledError):
        await day_task_b

    day_release_a.set()
    assert await day_task_a == "ok-day-a"
    day_ledger = json.loads((day_dir / "daily.json").read_text(encoding="utf-8"))
    assert day_ledger["uncertain"]["zhihu_search"] == 1


@pytest.mark.asyncio
async def test_low_remaining_concurrent_allows_second_blocks_third_and_cache_subtracts_uncertain(tmp_path):
    # 1. remaining=2, Request A reserves (prev_free=1, uncertain=1) before upstream deducts:
    # Request B must be allowed (available = min(2 - 1, 1) = 1), while Request C must be blocked.
    low_dir = tmp_path / "low_two"
    entered_1 = asyncio.Event()
    entered_2 = asyncio.Event()
    release_both = asyncio.Event()

    async def quota_two(group):
        return remaining(group, 2)

    async def exec_1():
        entered_1.set()
        await release_both.wait()
        return "ok-1"

    async def exec_2():
        entered_2.set()
        await release_both.wait()
        return "ok-2"

    async def exec_3():
        pytest.fail("third request must be blocked when only 2 free calls exist")

    policy = CallPolicy(directory=low_dir)
    t1 = asyncio.create_task(policy.run("/api/v1/content/zhihu_search", None, quota_two, exec_1))
    await entered_1.wait()
    t2 = asyncio.create_task(policy.run("/api/v1/content/zhihu_search", None, quota_two, exec_2))
    await entered_2.wait()

    with pytest.raises(CallBlocked, match="免费额度不足"):
        await policy.run("/api/v1/content/zhihu_search", None, quota_two, exec_3)

    release_both.set()
    assert await asyncio.gather(t1, t2) == ["ok-1", "ok-2"]
    final_ledger = json.loads((low_dir / "daily.json").read_text(encoding="utf-8"))
    assert final_ledger["calls"] == 2
    assert final_ledger["free"]["zhihu_search"] == 0
    assert final_ledger["uncertain"]["zhihu_search"] == 0

    # 2. Cached threshold checks floor - uncertain >= 20 rather than floor >= 20 alone.
    cache_dir = tmp_path / "cache_uncertain"
    cache_dir.mkdir()
    now_s = 1_767_225_600
    today = datetime.fromtimestamp(now_s, timezone(timedelta(hours=8))).date().isoformat()
    (cache_dir / "daily.json").write_text(
        json.dumps(
            {
                "version": 1,
                "day": today,
                "calls": 6,
                "uncertain": {"zhihu_search": 6},
                "free": {"zhihu_search": 25},
                "checked": {"zhihu_search": now_s - 5},
            }
        ),
        encoding="utf-8",
    )
    quota_queried = False

    async def fresh_quota(group):
        nonlocal quota_queried
        quota_queried = True
        return remaining(group, 25)

    async def simple_exec():
        return "ok"

    assert await CallPolicy(directory=cache_dir, now=lambda: float(now_s)).run(
        "/api/v1/content/zhihu_search", None, fresh_quota, simple_exec
    ) == "ok"
    assert quota_queried is True


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_cred", ["", "   ", "\t\n", 123, True])
async def test_invalid_blank_or_nonstring_credential_argument_fails_closed(tmp_path, bad_cred):
    async def quota(group):
        pytest.fail("quota must not run")

    async def execute():
        pytest.fail("business must not run")

    with pytest.raises(CallBlocked, match="凭证摘要无效"):
        await CallPolicy(directory=tmp_path).run(
            "/api/v1/content/zhihu_search", None, quota, execute, credential=bad_cred  # type: ignore[arg-type]
        )
    assert not (tmp_path / "daily.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_cred", [None, "", "   ", 123, []])
async def test_invalid_blank_or_null_stored_credential_in_ledger_fails_closed(tmp_path, stored_cred):
    today = datetime.fromtimestamp(time.time(), timezone(timedelta(hours=8))).date().isoformat()
    (tmp_path / "daily.json").write_text(
        json.dumps(
            {
                "version": 1,
                "day": today,
                "calls": 0,
                "uncertain": {},
                "free": {},
                "checked": {},
                "credential": stored_cred,
            }
        ),
        encoding="utf-8",
    )

    async def quota(group):
        pytest.fail("quota must not run")

    async def execute():
        pytest.fail("business must not run")

    with pytest.raises(CallBlocked, match="凭证摘要记录无效"):
        await CallPolicy(directory=tmp_path).run("/api/v1/content/zhihu_search", None, quota, execute)
