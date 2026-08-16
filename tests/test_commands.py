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
    mock.is_allowed.return_value = True
    snap = MagicMock()
    snap.to_line.return_value = "配额：搜索 0/100"
    snap.by_kind = {"search": {"used": 0, "limit": 100, "remaining": 100}}
    type(snap).used = PropertyMock(return_value=0)
    type(snap).limit = PropertyMock(return_value=100)
    type(snap).remaining = PropertyMock(return_value=100)
    mock.snapshot.return_value = snap
    mock.increment.return_value = snap
    return mock


def _mock_api_result(data):
    result = MagicMock()
    result.data = data
    result.quota = MagicMock()
    result.headers = {"x-request-id": "test-request"}
    return result


# ---------------------------------------------------------------------------
# generic runner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_command_handles_common_success_flow():
    mock_client = MagicMock(spec=ZhihuRestClient)
    mock_client.quota_tracker = _mock_tracker()
    api_result = _mock_api_result(["arbitrary", "payload"])
    call = AsyncMock(return_value=api_result)

    result = await commands._run_command("user", call, client=mock_client)

    assert result.success is True
    assert result.data == ["arbitrary", "payload"]
    assert result.quota is api_result.quota
    assert result.headers == {"x-request-id": "test-request"}
    call.assert_awaited_once_with(mock_client)
    mock_client.quota_tracker.is_allowed.assert_called_once_with("user")
    mock_client.quota_tracker.record_success.assert_called_once_with("user")


@pytest.mark.asyncio
async def test_run_command_records_rate_limit_failure():
    mock_client = MagicMock(spec=ZhihuRestClient)
    mock_client.quota_tracker = _mock_tracker()
    call = AsyncMock(side_effect=RateLimited("PDF 限流"))

    result = await commands._run_command("pdf", call, client=mock_client)

    assert result.success is False
    assert result.error == "PDF 限流"
    mock_client.quota_tracker.record_failure.assert_called_once_with("pdf")
    mock_client.quota_tracker.record_success.assert_not_called()


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


# ---------------------------------------------------------------------------
# new user / PDF / PPT wrappers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_user_contents_passes_all_options():
    mock_client = MagicMock()
    mock_client.quota_tracker = _mock_tracker()
    mock_client.user_contents = AsyncMock(
        return_value=_mock_api_result({"Items": [{"type": "answer"}]})
    )

    result = await commands.run_user_contents(
        content_type="answer",
        offset="next-offset",
        limit=7,
        sort_field="updated_time",
        sort_order="asc",
        oauth_token="oauth-user-token",
        client=mock_client,
    )

    assert result.success is True
    mock_client.user_contents.assert_awaited_once_with(
        content_type="answer",
        offset="next-offset",
        limit=7,
        sort_field="updated_time",
        sort_order="asc",
        oauth_token="oauth-user-token",
    )
    mock_client.quota_tracker.record_success.assert_called_once_with("user")


@pytest.mark.asyncio
async def test_run_favlist_contents_passes_identifier_and_pagination():
    mock_client = MagicMock()
    mock_client.quota_tracker = _mock_tracker()
    mock_client.favlist_contents = AsyncMock(
        return_value=_mock_api_result({"Items": []})
    )

    result = await commands.run_favlist_contents(
        favlist_id=42,
        offset=3,
        limit=9,
        oauth_token="oauth-user-token",
        client=mock_client,
    )

    assert result.success is True
    mock_client.favlist_contents.assert_awaited_once_with(
        favlist_url_token=None,
        favlist_id=42,
        offset=3,
        limit=9,
        oauth_token="oauth-user-token",
    )
    mock_client.quota_tracker.record_success.assert_called_once_with("user")


@pytest.mark.asyncio
async def test_run_knowledge_search_passes_scope_and_ids():
    mock_client = MagicMock()
    mock_client.quota_tracker = _mock_tracker()
    mock_client.knowledge_search = AsyncMock(
        return_value=_mock_api_result({"Items": []})
    )

    result = await commands.run_knowledge_search(
        "退款规则",
        knowledge_base_ids=["7526"],
        recall_scopes=["personal"],
        limit=8,
        client=mock_client,
    )

    assert result.success is True
    mock_client.knowledge_search.assert_awaited_once_with(
        query="退款规则",
        knowledge_base_ids=["7526"],
        recall_scopes=["personal"],
        limit=8,
    )
    mock_client.quota_tracker.record_success.assert_called_once_with("knowledge")


async def test_run_pdf_upload_accepts_non_dict_payload():
    mock_client = MagicMock()
    mock_client.quota_tracker = _mock_tracker()
    mock_client.upload_pdf = AsyncMock(
        return_value=_mock_api_result(["file-id", "ready"])
    )

    result = await commands.run_pdf_upload("document.pdf", client=mock_client)

    assert result.success is True
    assert result.data == ["file-id", "ready"]
    mock_client.upload_pdf.assert_awaited_once_with(file_path="document.pdf")
    mock_client.quota_tracker.record_success.assert_called_once_with("pdf")


@pytest.mark.asyncio
async def test_run_ppt_create_passes_task_options():
    mock_client = MagicMock()
    mock_client.quota_tracker = _mock_tracker()
    mock_client.create_ppt_generation_task = AsyncMock(
        return_value=_mock_api_result({"task_id": "ppt-task"})
    )

    result = await commands.run_ppt_create(
        "https://www.zhihu.com/question/1/answer/2",
        num_pages=15,
        idempotency_key="ppt-key",
        client=mock_client,
    )

    assert result.success is True
    mock_client.create_ppt_generation_task.assert_awaited_once_with(
        resource_url="https://www.zhihu.com/question/1/answer/2",
        num_pages=15,
        idempotency_key="ppt-key",
    )
    mock_client.quota_tracker.record_success.assert_called_once_with("ppt")
