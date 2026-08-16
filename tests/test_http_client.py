"""ZhihuRestClient 单元测试（respx mock）。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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
    PDF_MAX_BYTES,
    USER_PAGE_MAX,
    ZHIHU_SEARCH_MAX,
    BASE_URL,
    ZhihuRestClient,
)


SECRET = "zh1_testsecrettestsecr"


@pytest.fixture
def tracker(tmp_path):
    return QuotaTracker(base_dir=tmp_path)


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
    assert result.quota.by_kind["search"]["used"] == 1
    # 其它桶不应被计入
    assert result.quota.by_kind["trending"]["used"] == 0
    assert result.quota.by_kind["ask"]["used"] == 0


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
@pytest.mark.parametrize("count", [0, -1])
async def test_zhihu_search_nonpositive_count_uses_default(
    tracker, count: int
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            f"{BASE_URL}/api/v1/content/zhihu_search"
        ).mock(
            return_value=httpx.Response(
                200, json=_envelope(data={"Items": []})
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            await c.zhihu_search(query="RAG", count=count)
    assert route.calls.last.request.url.params["Count"] == str(
        ZHIHU_SEARCH_MAX
    )


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
    # 全网搜索与知乎站内搜索共用 search 桶
    assert tracker.snapshot().by_kind["search"]["used"] == 1


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
    assert result.quota.by_kind["trending"]["used"] == 1
    assert result.quota.by_kind["search"]["used"] == 0


@pytest.mark.asyncio
async def test_hot_list_clamped(tracker) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(200, json=_envelope(data={"Items": []}))
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            await c.hot_list(limit=999)
        assert route.calls.last.request.url.params["Limit"] == str(HOT_LIST_MAX)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1])
async def test_hot_list_nonpositive_limit_uses_default(
    tracker, limit: int
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{BASE_URL}/api/v1/content/hot_list").mock(
            return_value=httpx.Response(
                200, json=_envelope(data={"Items": []})
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            await c.hot_list(limit=limit)
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
    assert result.quota.by_kind["ask"]["used"] == 1
    assert result.quota.by_kind["search"]["used"] == 0


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
    # 失败调用不计入配额
    assert tracker.snapshot().by_kind["ask"]["used"] == 0


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
    # 401 不计入配额
    assert tracker.snapshot().by_kind["trending"]["used"] == 0


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
    # 限流失败不计入配额
    assert tracker.snapshot().by_kind["trending"]["used"] == 0


# ----------------------------------------------------------------------
# 用户数据
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_contents_contract_and_oauth_header(tracker) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{BASE_URL}/api/v1/user/contents").mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "Items": [
                            {
                                "ContentType": "answer",
                                "Url": "https://www.zhihu.com/answer/1",
                                "CreatedAt": 1745486539,
                                "LikeCount": 128,
                                "CommentCount": 12,
                                "FavoriteCount": 20,
                                "Title": "问题",
                                "Summary": "摘要",
                            }
                        ],
                        "Paging": {
                            "IsEnd": False,
                            "NextOffset": "cursor-20",
                            "Totals": 100,
                        },
                    }
                ),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            result = await c.user_contents(
                content_type="answer",
                offset="cursor-20",
                limit=USER_PAGE_MAX,
                sort_field="like_count",
                sort_order="asc",
                oauth_token="oauth-user-token",
            )

    request = route.calls.last.request
    assert dict(request.url.params) == {
        "Offset": "cursor-20",
        "Limit": str(USER_PAGE_MAX),
        "ContentType": "answer",
        "SortField": "like_count",
        "SortOrder": "asc",
    }
    assert request.headers["X-OAuth-Token"] == "oauth-user-token"
    assert request.headers["Authorization"] == f"Bearer {SECRET}"
    assert request.headers["X-Request-Timestamp"].isdigit()
    assert result.data["Paging"]["NextOffset"] == "cursor-20"
    assert result.quota.by_kind["user"]["used"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"content_type": "video"},
        {"sort_field": "created_at"},
        {"sort_order": "newest"},
        {"offset": -1},
        {"offset": ""},
        {"limit": 0},
        {"limit": USER_PAGE_MAX + 1},
    ],
)
async def test_user_contents_rejects_invalid_documented_values(
    tracker, kwargs
) -> None:
    async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
        with pytest.raises(InvalidArguments):
            await c.user_contents(**kwargs)
    assert tracker.snapshot().by_kind["user"]["used"] == 0


@pytest.mark.asyncio
async def test_user_followees_accepts_string_offset(tracker) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{BASE_URL}/api/v1/user/followees").mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "Items": [
                            {
                                "Fullname": "知乎用户",
                                "UrlToken": "example",
                                "Url": "https://www.zhihu.com/people/example",
                                "AvatarUrl": "https://picx.zhimg.com/example.jpg",
                                "Headline": "简介",
                                "Gender": 0,
                                "FollowerCount": 1000,
                            }
                        ],
                        "Paging": {
                            "IsEnd": True,
                            "Totals": 1,
                        },
                    }
                ),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            result = await c.user_followees(offset="20", limit=25)

    request = route.calls.last.request
    assert request.url.params["Offset"] == "20"
    assert request.url.params["Limit"] == "25"
    assert "X-OAuth-Token" not in request.headers
    assert result.data["Items"][0]["UrlToken"] == "example"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "path"),
    [
        ("user_collections", "/api/v1/user/collections"),
        ("user_favlists", "/api/v1/user/favlists"),
    ],
)
async def test_user_limit_only_operations(
    tracker, method_name: str, path: str
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{BASE_URL}{path}").mock(
            return_value=httpx.Response(
                200, json=_envelope(data={"Items": []})
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            method = getattr(c, method_name)
            await method(limit=51, oauth_token="oauth-token")

    request = route.calls.last.request
    assert dict(request.url.params) == {"Limit": "51"}
    assert request.headers["X-OAuth-Token"] == "oauth-token"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("identifier", "expected_param"),
    [
        ({"favlist_url_token": 123456789}, "FavlistUrlToken"),
        ({"favlist_id": 987654321}, "FavlistId"),
    ],
)
async def test_favlist_contents_identifier_contract(
    tracker, identifier: dict[str, int], expected_param: str
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            f"{BASE_URL}/api/v1/user/favlist_contents"
        ).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "Items": [],
                        "Paging": {
                            "IsEnd": True,
                            "Totals": 0,
                        },
                    }
                ),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            await c.favlist_contents(
                **identifier,
                offset="next-page",
                limit=20,
                oauth_token="oauth-token",
            )

    request = route.calls.last.request
    assert request.url.params[expected_param] == str(
        next(iter(identifier.values()))
    )
    other_param = (
        "FavlistId"
        if expected_param == "FavlistUrlToken"
        else "FavlistUrlToken"
    )
    assert other_param not in request.url.params
    assert request.url.params["Offset"] == "next-page"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"favlist_url_token": 1, "favlist_id": 2},
        {"favlist_url_token": 0},
        {"favlist_id": -1},
        {"favlist_id": 1, "limit": 0},
    ],
)
async def test_favlist_contents_rejects_invalid_identifiers(
    tracker, kwargs
) -> None:
    async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
        with pytest.raises(InvalidArguments):
            await c.favlist_contents(**kwargs)


# ----------------------------------------------------------------------
# 知识库
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_bases_contract(tracker) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{BASE_URL}/api/v1/knowledge/bases").mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "Items": [
                            {
                                "KnowledgeBaseID": "7526139256098382426",
                                "Name": "产品资料",
                                "Relation": "created",
                                "IsDefault": False,
                                "Visibility": "private",
                                "ContentCount": 12,
                                "UpdatedAt": 1785902400,
                            }
                        ]
                    }
                ),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            result = await c.knowledge_bases(scope="created")

    assert dict(route.calls.last.request.url.params) == {"Scope": "created"}
    assert result.data["Items"][0]["KnowledgeBaseID"] == "7526139256098382426"
    assert result.quota.by_kind["knowledge"]["used"] == 1


@pytest.mark.asyncio
async def test_knowledge_items_passes_opaque_cursor(tracker) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            f"{BASE_URL}/api/v1/knowledge/bases/7526139256098382426/items"
        ).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "Items": [],
                        "Total": 12,
                        "HasMore": True,
                        "NextCursor": "next-cursor",
                    }
                ),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            result = await c.knowledge_items(
                "7526139256098382426",
                cursor="next-cursor",
                limit=20,
            )

    assert dict(route.calls.last.request.url.params) == {
        "Limit": "20",
        "Cursor": "next-cursor",
    }
    assert result.data["NextCursor"] == "next-cursor"


@pytest.mark.asyncio
async def test_knowledge_search_requires_scope_or_ids(tracker) -> None:
    async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
        with pytest.raises(InvalidArguments, match="至少"):
            await c.knowledge_search("退款规则")
    assert tracker.snapshot().by_kind["knowledge"]["used"] == 0


@pytest.mark.asyncio
async def test_knowledge_search_contract(tracker) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{BASE_URL}/api/v1/knowledge/search").mock(
            return_value=httpx.Response(
                200,
                json=_envelope(data={"Items": []}),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            await c.knowledge_search(
                " 退款规则 ",
                knowledge_base_ids=["7526139256098382426"],
                recall_scopes=["personal"],
                limit=10,
            )

    assert json.loads(route.calls.last.request.content) == {
        "Query": "退款规则",
        "Limit": 10,
        "KnowledgeBaseIDs": ["7526139256098382426"],
        "RecallScopes": ["personal"],
    }


@pytest.mark.asyncio
async def test_upload_knowledge_file_uses_documented_form_fields(
    tracker, tmp_path
) -> None:
    pdf = tmp_path / "产品资料.pdf"
    pdf.write_bytes(b"%PDF-1.7\nknowledge")
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{BASE_URL}/api/v1/knowledge/files").mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "KnowledgeBaseID": "7526139256098382426",
                        "RecallContentID": "recall-content-id",
                        "FileName": "产品资料.pdf",
                        "FileSize": 18,
                    }
                ),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            result = await c.upload_knowledge_file(
                pdf, knowledge_base_id="7526139256098382426"
            )

    request = route.calls.last.request
    content_type = request.headers["Content-Type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    body = await request.aread()
    assert 'name="File"; filename="产品资料.pdf"'.encode("utf-8") in body
    assert b"name=\"KnowledgeBaseID\"" in body
    assert b"7526139256098382426" in body
    assert result.data["RecallContentID"] == "recall-content-id"
    assert result.quota.by_kind["knowledge"]["used"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"scope": "mine"},
        {"knowledge_base_id": ""},
        {"limit": 21},
        {"recall_scopes": ["private"]},
    ],
)
async def test_knowledge_operations_reject_invalid_values(
    tracker, kwargs
) -> None:
    async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
        if "scope" in kwargs:
            with pytest.raises(InvalidArguments):
                await c.knowledge_bases(**kwargs)
        elif "recall_scopes" in kwargs:
            with pytest.raises(InvalidArguments):
                await c.knowledge_search("问题", **kwargs)
        elif "knowledge_base_id" in kwargs:
            with pytest.raises(InvalidArguments):
                await c.knowledge_items(**kwargs)
        else:
            with pytest.raises(InvalidArguments):
                await c.knowledge_items("7526", **kwargs)


# ----------------------------------------------------------------------
# PDF 解析
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_pdf_uses_multipart_without_json_content_type(
    tracker, tmp_path
) -> None:
    pdf = tmp_path / "example.pdf"
    pdf.write_bytes(b"%PDF-1.7\ncontract-test")
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{BASE_URL}/resources/v1/files").mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "file_id": "file_00000000fb987230beba394fd8279daf"
                    }
                ),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            result = await c.upload_pdf(pdf)

    request = route.calls.last.request
    content_type = request.headers["Content-Type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    body = await request.aread()
    assert b'name="file"; filename="example.pdf"' in body
    assert b"Content-Type: application/pdf" in body
    assert b"%PDF-1.7" in body
    assert result.data["file_id"].startswith("file_")
    assert result.quota.by_kind["pdf"]["used"] == 1


@pytest.mark.asyncio
async def test_upload_pdf_rejects_wrong_type_and_oversize(
    tracker, tmp_path, monkeypatch
) -> None:
    text_file = tmp_path / "example.txt"
    text_file.write_text("not pdf", encoding="utf-8")
    async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
        with pytest.raises(InvalidArguments, match="pdf"):
            await c.upload_pdf(text_file)

    pdf = tmp_path / "oversize.pdf"
    pdf.write_bytes(b"%PDF")
    real_stat = pdf.stat()
    fake_stat = SimpleNamespace(
        st_mode=real_stat.st_mode,
        st_size=PDF_MAX_BYTES + 1,
    )
    path_type = type(pdf)
    original_stat = path_type.stat
    with monkeypatch.context() as patcher:
        patcher.setattr(
            path_type,
            "stat",
            lambda self, *args, **kwargs: (
                fake_stat
                if self == pdf
                else original_stat(self, *args, **kwargs)
            ),
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            with pytest.raises(InvalidArguments, match="100MB"):
                await c.upload_pdf(pdf)


@pytest.mark.asyncio
async def test_pdf_task_create_and_status_contract(tracker) -> None:
    task_id = "pdf_39b0e572b738a5ce8c5be600f9cf7b91"
    with respx.mock(assert_all_called=True) as router:
        create_route = router.post(
            f"{BASE_URL}/api/v1/pdf-parse/tasks"
        ).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "task_id": task_id,
                        "task_status": "pending",
                    }
                ),
            )
        )
        status_route = router.get(
            f"{BASE_URL}/api/v1/pdf-parse/tasks/{task_id}"
        ).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "task_id": task_id,
                        "task_status": "succeeded",
                        "progress": 1,
                        "result": {
                            "url": "https://example.test/result.json",
                            "summary": "摘要",
                            "expires_at_ms": 1782800000000,
                        },
                        "error": None,
                    }
                ),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            created = await c.create_pdf_parse_task(
                "file_abc", idempotency_key="pdf-request-001"
            )
            status = await c.get_pdf_parse_task(task_id)

    create_request = create_route.calls.last.request
    assert json.loads(create_request.content) == {"file_id": "file_abc"}
    assert create_request.headers["Idempotency-Key"] == "pdf-request-001"
    assert dict(status_route.calls.last.request.url.params) == {}
    assert created.data["task_status"] == "pending"
    assert status.data["result"]["summary"] == "摘要"
    assert status.quota.by_kind["pdf"]["used"] == 2


# ----------------------------------------------------------------------
# PPT 生成
# ----------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource_url",
    [
        "https://www.zhihu.com/question/123/answer/456",
        "https://www.zhihu.com/answer/456",
        "https://zhuanlan.zhihu.com/p/789",
    ],
)
async def test_ppt_task_create_accepts_documented_urls(
    tracker, resource_url: str
) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(
            f"{BASE_URL}/api/v1/ppt-generation/tasks"
        ).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "task_id": "ppt_task",
                        "task_status": "pending",
                    }
                ),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            await c.create_ppt_generation_task(
                resource_url,
                21,
                idempotency_key="ppt-request-001",
            )

    request = route.calls.last.request
    assert json.loads(request.content) == {
        "resource_url": resource_url,
        "num_pages": 21,
    }
    assert request.headers["Idempotency-Key"] == "ppt-request-001"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("resource_url", "num_pages"),
    [
        ("https://www.zhihu.com/question/123", 12),
        ("http://www.zhihu.com/answer/456", 12),
        ("https://example.com/answer/456", 12),
        ("https://www.zhihu.com/answer/456", 5),
        ("https://www.zhihu.com/answer/456", 22),
        ("https://www.zhihu.com/answer/456", True),
    ],
)
async def test_ppt_task_create_rejects_unsupported_input(
    tracker, resource_url: str, num_pages: int
) -> None:
    async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
        with pytest.raises(InvalidArguments):
            await c.create_ppt_generation_task(resource_url, num_pages)


@pytest.mark.asyncio
async def test_get_ppt_generation_task_contract(tracker) -> None:
    task_id = "ppt_39b0e572b738a5ce8c5be600f9cf7b91"
    with respx.mock(assert_all_called=True) as router:
        router.get(
            f"{BASE_URL}/api/v1/ppt-generation/tasks/{task_id}"
        ).mock(
            return_value=httpx.Response(
                200,
                json=_envelope(
                    data={
                        "task_id": task_id,
                        "task_status": "running",
                        "progress": 0.45,
                        "result": None,
                        "error": None,
                    }
                ),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            result = await c.get_ppt_generation_task(task_id)

    assert result.data["progress"] == 0.45
    assert result.quota.by_kind["ppt"]["used"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "task_id"),
    [
        ("get_pdf_parse_task", "../../api/v1/user/contents"),
        ("get_pdf_parse_task", "pdf_../../api/v1/user/contents"),
        ("get_pdf_parse_task", "ppt_wrong_prefix"),
        ("get_pdf_parse_task", "pdf_%2e%2e"),
        ("get_ppt_generation_task", "../content/hot_list"),
        ("get_ppt_generation_task", "ppt_../content/hot_list"),
        ("get_ppt_generation_task", "pdf_wrong_prefix"),
        ("get_ppt_generation_task", "ppt_..\\content"),
    ],
)
async def test_task_status_rejects_path_traversal_before_request(
    tracker, method_name: str, task_id: str
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_envelope(), request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url=BASE_URL, transport=transport
    ) as upstream:
        async with ZhihuRestClient(
            SECRET, client=upstream, quota_tracker=tracker
        ) as c:
            method = getattr(c, method_name)
            with pytest.raises(InvalidArguments, match="task_id"):
                await method(task_id)

    assert requests == []


# ----------------------------------------------------------------------
# 新错误码
# ----------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "error_type"),
    [
        (30002, RateLimited),
        (40001, InvalidArguments),
        (40002, InvalidArguments),
        (40003, RateLimited),
        (40004, InvalidArguments),
        (40005, InvalidArguments),
        (40006, InvalidArguments),
        (50002, UpstreamUnavailable),
    ],
)
async def test_new_documented_error_code_mapping(
    tracker, code: int, error_type: type[Exception]
) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{BASE_URL}/api/v1/pdf-parse/tasks").mock(
            return_value=httpx.Response(
                200,
                json=_envelope(code=code, message=f"error-{code}"),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            with pytest.raises(error_type, match=f"error-{code}"):
                await c.create_pdf_parse_task("file_abc")

    assert tracker.snapshot().by_kind["pdf"]["used"] == 0


@pytest.mark.asyncio
async def test_documented_error_code_mapping_survives_http_400(
    tracker,
) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{BASE_URL}/api/v1/pdf-parse/tasks").mock(
            return_value=httpx.Response(
                400,
                json=_envelope(
                    code=40002,
                    message="file is expired",
                ),
            )
        )
        async with ZhihuRestClient(SECRET, quota_tracker=tracker) as c:
            with pytest.raises(InvalidArguments, match="file is expired"):
                await c.create_pdf_parse_task("file_expired")
