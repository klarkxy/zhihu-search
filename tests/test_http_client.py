"""ZhihuRestClient 单元测试（respx mock）。"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from zhihu_search.quota import QuotaTracker
from zhihu_search.upstream.base import (
    InvalidArguments,
    RateLimited,
    TokenInvalid,
    UpstreamTimeout,
    UpstreamUnavailable,
)
from zhihu_search.upstream.http_client import (
    GLOBAL_SEARCH_MAX,
    HOT_LIST_MAX,
    ZHIHU_SEARCH_MAX,
    BASE_URL,
    ZhihuRestClient,
)


SECRET = "zh1_testsecrettestsecr"


@pytest.fixture
def tracker(tmp_path):
    return QuotaTracker(base_dir=tmp_path, daily_limit=100)


def _envelope(code: int = 0, data: dict | None = None, message: str = "success") -> dict:
    return {"Code": code, "Message": message, "Data": data or {}}


# ----------------------------------------------------------------------
# 知乎搜索
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zhihu_search_success(tracker) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/zhihu_search").mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "HasMore": False,
                        "Items": [
                            {
                                "Title": "RAG 评测方法综述",
                                "ContentType": "Article",
                                "Url": "https://zhuanlan.zhihu.com/p/123",
                                "VoteUpCount": 128,
                                "CommentCount": 15,
                                "AuthorName": "张三",
                                "AuthorityLevel": "2",
                                "EditTime": 1710000000,
                                "ContentText": "本文介绍了...",
                            }
                        ],
                    }
                ),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            result = await c.zhihu_search(query="RAG", count=5)

    assert result.data["Items"][0]["Title"] == "RAG 评测方法综述"
    assert result.quota.used == 1
    assert result.quota.limit == 100


@pytest.mark.asyncio
async def test_zhihu_search_count_clamped(tracker) -> None:
    """count > 最大值时会被服务端截断，我们这里只发出去，校验截断在客户端层不做。

    服务器会自己截断到 10，我们的代码负责发送。
    """
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE_URL}/api/v1/content/zhihu_search").mock(
            return_value=httpx.Response(200, json=_envelope(data={"Items": []}))
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            await c.zhihu_search(query="RAG", count=999)
        # 校验实际发出去的 URL 参数中 Count 被截断
        request = route.calls.last.request
        assert request.url.params["Count"] == str(ZHIHU_SEARCH_MAX)


@pytest.mark.asyncio
async def test_zhihu_search_invalid_query(tracker) -> None:
    async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
        with pytest.raises(InvalidArguments):
            await c.zhihu_search(query="x")
        with pytest.raises(InvalidArguments):
            await c.zhihu_search(query="x" * 200)


# ----------------------------------------------------------------------
# 全网搜索
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_search_with_filter(tracker) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE_URL}/api/v1/content/global_search").mock(
            return_value=httpx.Response(200, json=_envelope(data={"Items": []}))
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            await c.global_search(
                query="AI",
                count=15,
                filter='host=="example.com"',
                search_db="realtime",
            )
        request = route.calls.last.request
        assert request.url.params["Filter"] == 'host=="example.com"'
        assert request.url.params["SearchDB"] == "realtime"
        assert request.url.params["Count"] == "15"


@pytest.mark.asyncio
async def test_global_search_omits_empty_filter(tracker) -> None:
    """filter 为空时不应该出现在 URL 里。"""
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE_URL}/api/v1/content/global_search").mock(
            return_value=httpx.Response(200, json=_envelope(data={"Items": []}))
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            await c.global_search(query="AI")
        request = route.calls.last.request
        assert "Filter" not in request.url.params


# ----------------------------------------------------------------------
# 热榜
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hot_list(tracker) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "Total": 1,
                        "Items": [
                            {
                                "Title": "热点 1",
                                "Url": "https://www.zhihu.com/question/1",
                                "ThumbnailUrl": "",
                                "Summary": "摘要",
                            }
                        ],
                    }
                ),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            result = await c.hot_list(limit=10)
    assert result.data["Items"][0]["Title"] == "热点 1"


@pytest.mark.asyncio
async def test_hot_list_clamped(tracker) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(200, json=_envelope(data={"Items": []}))
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            await c.hot_list(limit=999)
        assert route.calls.last.request.url.params["Limit"] == str(HOT_LIST_MAX)


# ----------------------------------------------------------------------
# 直答
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zhida_success(tracker) -> None:
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
                                "content": "Rave 文化最早在英国兴起。",
                                "reasoning_content": "先分析背景...",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            result = await c.zhida(query="什么是 rave 文化")
    assert "Rave 文化最早在英国兴起" in result.data["content"]
    assert result.data["reasoning_content"] == "先分析背景..."
    assert result.quota.used == 1


@pytest.mark.asyncio
async def test_zhida_error_response(tracker) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{BASE_URL}/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={"error": {"message": "bad model", "type": "invalid_request_error"}},
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            with pytest.raises(UpstreamUnavailable) as exc_info:
                await c.zhida(query="x")
    assert "bad model" in str(exc_info.value)


# ----------------------------------------------------------------------
# 错误映射
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_invalid_401(tracker) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            with pytest.raises(TokenInvalid):
                await c.hot_list()


@pytest.mark.asyncio
async def test_rate_limited_envelope(tracker) -> None:
    """响应信封 Code=30001 也算限流。"""
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(200, json=_envelope(code=30001, message="触发限流"))
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            with pytest.raises(RateLimited):
                await c.hot_list()


@pytest.mark.asyncio
async def test_http_429(tracker) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "10"}, text="slow")
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            with pytest.raises(RateLimited) as exc_info:
                await c.hot_list()
    assert exc_info.value.retry_after == 10.0


@pytest.mark.asyncio
async def test_internal_error(tracker) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(200, json=_envelope(code=90001, message="oops"))
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            with pytest.raises(UpstreamUnavailable):
                await c.hot_list()


@pytest.mark.asyncio
async def test_5xx(tracker) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(503, text="down")
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            with pytest.raises(UpstreamUnavailable):
                await c.hot_list()


@pytest.mark.asyncio
async def test_timeout(tracker) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            side_effect=httpx.TimeoutException("slow")
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker, timeout=0.1) as c:
            with pytest.raises(UpstreamTimeout):
                await c.hot_list()


@pytest.mark.asyncio
async def test_non_json_response(tracker) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(200, text="<html>oops</html>")
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            with pytest.raises(UpstreamUnavailable):
                await c.hot_list()


# ----------------------------------------------------------------------
# 配额累加
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quota_increments_on_each_call(tracker) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(200, json=_envelope(data={"Items": []}))
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            await c.hot_list()
            await c.hot_list()
            await c.hot_list()
            snap = c.quota_tracker.snapshot()
    assert snap.used == 3
    assert snap.remaining == 97


@pytest.mark.asyncio
async def test_quota_does_not_increment_on_error(tracker) -> None:
    """失败调用不应该计入配额（避免重试刷高计数）。"""
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(401, text="bad")
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            from contextlib import suppress
            with suppress(TokenInvalid):
                await c.hot_list()
            snap = c.quota_tracker.snapshot()
    assert snap.used == 0