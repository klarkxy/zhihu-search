"""commands.py 单元测试。

通过传入 mock client 测试 commands.run_* 的 CommandResult 结构。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import httpx
import pytest
import respx

from zhihu_search import commands
from zhihu_search.quota import QuotaTracker
from zhihu_search.upstream.base import (
    RateLimited,
    TokenInvalid,
)
from zhihu_search.upstream.http_client import (
    BASE_URL,
    ZhihuRestClient,
)


SECRET = "zh1_testsecrettestsecr"


def _envelope(code: int = 0, data: dict | None = None) -> dict:
    return {"Code": code, "Message": "success", "Data": data or {}}


def _mock_tracker() -> MagicMock:
    """返回一个 MagicMock 替换 QuotaTracker，避免磁盘 IO。"""
    mock = MagicMock(spec=QuotaTracker)
    snap = MagicMock()
    snap.to_line.return_value = "配额：搜索 0/100"
    snap.by_kind = {"search": {"used": 0, "limit": 100, "remaining": 100}}
    type(snap).used = PropertyMock(return_value=0)
    type(snap).limit = PropertyMock(return_value=100)
    type(snap).remaining = PropertyMock(return_value=100)
    mock.snapshot.return_value = snap
    mock.increment.return_value = snap
    return mock


# ---------------------------------------------------------------------------
# run_search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_search_zhihu_success():
    """站内搜索成功 → CommandResult.success=True, data 有值。"""
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/zhihu_search").mock(
            return_value=httpx.Response(
                200,
                json=_envelope(data={"Items": [{"Title": "RAG 评测"}]}),
            )
        )
        async with ZhihuRestClient(SECRET) as client:
            result = await commands.run_search(query="RAG", scope="zhihu", count=5, client=client)

    assert result.success is True
    assert result.error is None
    assert result.data is not None
    assert result.data["Items"][0]["Title"] == "RAG 评测"
    # 复用客户端 → quota 有值
    assert result.quota is not None


@pytest.mark.asyncio
async def test_run_search_global_success():
    """全网搜索成功。"""
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/global_search").mock(
            return_value=httpx.Response(200, json=_envelope(data={"Items": []}))
        )
        async with ZhihuRestClient(SECRET) as client:
            result = await commands.run_search(
                query="AI", scope="web", count=15, filter='host=="example.com"', client=client
            )

    assert result.success is True
    assert result.error is None


@pytest.mark.asyncio
async def test_run_search_handles_token_invalid():
    """401 → CommandResult.success=False, error 有值。"""
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/zhihu_search").mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )
        async with ZhihuRestClient(SECRET) as client:
            result = await commands.run_search(query="test", client=client)

    assert result.success is False
    assert result.error is not None
    assert "Token" in result.error  # TokenInvalid 的消息


@pytest.mark.asyncio
async def test_run_search_handles_rate_limit():
    """限流 → CommandResult.success=False。"""
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/zhihu_search").mock(
            return_value=httpx.Response(
                200, json=_envelope(code=30001, data=None)
            )
        )
        async with ZhihuRestClient(SECRET) as client:
            result = await commands.run_search(query="test", client=client)

    assert result.success is False
    assert "限流" in (result.error or "")


@pytest.mark.asyncio
async def test_run_search_handles_generic_exception():
    """非 McpError 异常 → CommandResult.success=False。"""
    mock_client = MagicMock(spec=ZhihuRestClient)
    mock_client.zhihu_search = AsyncMock(side_effect=RuntimeError("网络断开"))
    # client 的 quota_tracker 属性需要 mock
    mock_client.quota_tracker = _mock_tracker()

    result = await commands.run_search(query="test", client=mock_client)

    assert result.success is False
    assert "未预期错误" in (result.error or "")
    assert "网络断开" in (result.error or "")


# ---------------------------------------------------------------------------
# run_ask
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_ask_success():
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BASE_URL}/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "chatcmpl-xxx",
                    "model": "zhida-fast-1p5",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "Python 是一种语言。",
                                "reasoning_content": "",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        )
        async with ZhihuRestClient(SECRET) as client:
            result = await commands.run_ask(query="什么是Python", client=client)

    assert result.success is True
    assert result.data is not None
    assert "Python 是一种语言" in result.data["content"]


@pytest.mark.asyncio
async def test_run_ask_model_mapping():
    """model 参数正确映射到上游模型名。"""
    with respx.mock(assert_all_called=False) as router:
        route = router.post(f"{BASE_URL}/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "x",
                    "model": "zhida-thinking-1p5",
                    "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": "ok"}}
                    ],
                },
            )
        )
        async with ZhihuRestClient(SECRET) as client:
            await commands.run_ask(query="test", model="thinking", client=client)

        assert json.loads(route.calls.last.request.content)["model"] == "zhida-thinking-1p5"


# ---------------------------------------------------------------------------
# run_trending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_trending_success():
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "Total": 1,
                        "Items": [{"Title": "热点1", "Url": "https://zhihu.com/q/1"}],
                    }
                ),
            )
        )
        async with ZhihuRestClient(SECRET) as client:
            result = await commands.run_trending(limit=5, client=client)

    assert result.success is True
    assert result.data["Items"][0]["Title"] == "热点1"


@pytest.mark.asyncio
async def test_run_trending_error():
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(429)
        )
        async with ZhihuRestClient(SECRET) as client:
            result = await commands.run_trending(client=client)

    assert result.success is False
    assert result.error is not None
