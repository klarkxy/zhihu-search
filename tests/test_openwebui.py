"""openwebui.py 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from zhihu_search import openwebui
from zhihu_search.commands import CommandResult


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    """Keep host credentials from changing auth and OAuth test behavior."""
    monkeypatch.delenv(openwebui.API_KEY_ENV, raising=False)
    monkeypatch.delenv(openwebui.OAUTH_TOKEN_ENV, raising=False)
    openwebui._client = None
    yield
    openwebui._client = None


def _client(api_key: str | None = "test-key") -> TestClient:
    return TestClient(openwebui.create_app(api_key=api_key))


def test_openapi_declares_bearer_auth() -> None:
    """OpenAPI schema 使用标准 HTTP bearer 认证方案。"""
    client = _client()

    schema = client.get("/openapi.json").json()

    scheme = schema["components"]["securitySchemes"]["BearerAuth"]
    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"
    assert schema["paths"]["/search"]["post"]["security"] == [{"BearerAuth": []}]


def test_openapi_exposes_every_model_safe_new_operation() -> None:
    """New user/task operations share the same bearer-protected router."""
    schema = _client().get("/openapi.json").json()
    expected = {
        "/quota": "quota",
        "/user/contents": "user_contents",
        "/user/followees": "user_followees",
        "/user/collections": "user_collections",
        "/user/favlists": "user_favlists",
        "/user/favlist-contents": "favlist_contents",
        "/knowledge/bases": "knowledge_bases",
        "/knowledge/items": "knowledge_items",
        "/knowledge/search": "knowledge_search",
        "/pdf/create": "pdf_create",
        "/pdf/status": "pdf_status",
        "/ppt/create": "ppt_create",
        "/ppt/status": "ppt_status",
    }
    for path, operation_id in expected.items():
        operation = schema["paths"][path]["post"]
        assert operation["operationId"] == operation_id
        assert operation["security"] == [{"BearerAuth": []}]

    # Deliberate secret/file safety boundary.
    assert "/pdf/upload" not in schema["paths"]
    assert "/knowledge/upload" not in schema["paths"]
    assert "/knowledge/files" not in schema["paths"]
    assert not any(path.startswith("/oauth") for path in schema["paths"])
    quota_schema = schema["components"]["schemas"]["QuotaRequest"]
    assert quota_schema["properties"]["api_ids"]["items"]["enum"] == [
        "global_search",
        "zhihu_search",
        "hot_list",
        "user_data",
        "zhida_openai",
        "knowledge",
        "tools",
    ]
    user_schema = schema["components"]["schemas"]["UserContentsRequest"]
    assert "oauth_token" not in user_schema["properties"]
    assert "use_configured_oauth_user" in user_schema["properties"]
    assert user_schema["properties"]["offset"]["anyOf"] == [
        {"type": "integer", "minimum": 0.0},
        {"type": "string", "minLength": 1},
    ]

    favlist_schema = schema["components"]["schemas"]["FavlistContentsRequest"]
    assert len(favlist_schema["oneOf"]) == 2
    assert (
        favlist_schema["properties"]["favlist_url_token"]["anyOf"][0][
            "minimum"
        ]
        == 1.0
    )
    assert (
        schema["components"]["schemas"]["PdfStatusRequest"]["properties"][
            "task_id"
        ]["pattern"]
        == r"^pdf_[A-Za-z0-9_-]+$"
    )
    assert (
        schema["components"]["schemas"]["PptStatusRequest"]["properties"][
            "task_id"
        ]["pattern"]
        == r"^ppt_[A-Za-z0-9_-]+$"
    )


def test_openapi_does_not_claim_auth_when_server_key_is_disabled(
    monkeypatch,
) -> None:
    monkeypatch.delenv(openwebui.API_KEY_ENV, raising=False)
    schema = openwebui.create_app(api_key=None).openapi()
    assert "security" not in schema["paths"]["/user/contents"]["post"]


def test_api_key_is_isolated_per_app_instance(monkeypatch) -> None:
    """Creating an authless app must not disable an already-secured app."""
    monkeypatch.delenv(openwebui.API_KEY_ENV, raising=False)
    secured = TestClient(openwebui.create_app(api_key="secret"))
    openwebui.create_app(api_key=None)

    response = secured.post("/search", json={"query": "RAG"})
    assert response.status_code == 401


def test_explicit_empty_api_key_disables_environment_key(monkeypatch) -> None:
    monkeypatch.setenv(openwebui.API_KEY_ENV, "from-env")
    schema = openwebui.create_app(api_key="").openapi()
    assert "security" not in schema["paths"]["/search"]["post"]


def test_tool_endpoint_requires_bearer_token() -> None:
    """启用 api_key 后，工具接口无 token 返回 401。"""
    client = _client(api_key="secret")

    response = client.post("/search", json={"query": "RAG"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"
    assert response.headers["www-authenticate"] == "Bearer"


def test_tool_endpoint_accepts_bearer_token() -> None:
    """带正确 bearer token 时可以调用工具。"""
    client = _client(api_key="secret")

    with (
        patch.object(openwebui, "_get_client", return_value=object()),
        patch(
            "zhihu_search.openwebui.commands.run_search",
            new=AsyncMock(
                return_value=CommandResult(
                    success=True,
                    data={"Items": [{"Title": "RAG 评测", "Url": "https://example.com"}]},
                )
            ),
        ),
    ):
        response = client.post(
            "/search",
            json={"query": "RAG", "scope": "zhihu", "count": 3},
            headers={"Authorization": "Bearer secret"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["kind"] == "search"
    assert "RAG 评测" in payload["content"]


def test_tool_endpoint_can_run_without_auth() -> None:
    """未配置 api_key 时，适合本机私有网络调试。"""
    client = _client(api_key=None)

    with (
        patch.object(openwebui, "_get_client", return_value=object()),
        patch(
            "zhihu_search.openwebui.commands.run_trending",
            new=AsyncMock(
                return_value=CommandResult(
                    success=True,
                    data={"Items": [{"Title": "热点", "Url": "https://example.com"}]},
                )
            ),
        ),
    ):
        response = client.post("/trending", json={"limit": 1})

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_quota_route_uses_official_filter_without_local_quota_field() -> None:
    client = _client(api_key=None)
    run_quota = AsyncMock(
        return_value=CommandResult(
            success=True,
            data=[
                {
                    "APIID": "knowledge",
                    "APIName": "知识库",
                    "TotalQuota": 100,
                    "TotalUsed": 12,
                    "RemainingQuota": 88,
                }
            ],
        )
    )
    with (
        patch.object(openwebui, "_get_client", return_value=object()),
        patch("zhihu_search.openwebui.commands.run_quota", new=run_quota),
    ):
        response = client.post("/quota", json={"api_ids": ["knowledge"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "quota"
    assert payload["data"][0]["RemainingQuota"] == 88
    assert "quota" not in payload
    run_quota.assert_awaited_once()
    assert run_quota.await_args.kwargs["api_ids"] == ["knowledge"]
    assert run_quota.await_args.kwargs["client"] is not None


def test_user_contents_route_uses_server_side_oauth_and_pagination(
    monkeypatch,
) -> None:
    """OAuth stays in server configuration, while NextOffset remains a tool input."""
    monkeypatch.setenv(openwebui.OAUTH_TOKEN_ENV, "oauth-user-token")
    client = _client(api_key=None)
    run_user_contents = AsyncMock(
        return_value=CommandResult(
            success=True,
            data={"Items": [], "Paging": {"IsEnd": True, "Totals": 0}},
        )
    )
    with (
        patch.object(openwebui, "_get_client", return_value=object()),
        patch(
            "zhihu_search.openwebui.commands.run_user_contents",
            new=run_user_contents,
        ),
    ):
        response = client.post(
            "/user/contents",
            json={
                "content_type": "answer",
                "offset": "next-20",
                "limit": 12,
                "sort_field": "like_count",
                "sort_order": "asc",
                "use_configured_oauth_user": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["kind"] == "user_contents"
    kwargs = run_user_contents.await_args.kwargs
    assert kwargs["offset"] == "next-20"
    assert kwargs["oauth_token"] == "oauth-user-token"
    assert kwargs["client"] is not None

    rejected_secret = client.post(
        "/user/contents",
        json={"content_type": "all", "oauth_token": "must-not-be-in-body"},
    )
    assert rejected_secret.status_code == 422


def test_knowledge_search_requires_scope_or_ids() -> None:
    client = _client(api_key=None)
    missing = client.post("/knowledge/search", json={"query": "退款规则"})
    assert missing.status_code == 422


def test_favlist_contents_requires_exactly_one_identifier() -> None:
    client = _client(api_key=None)
    missing = client.post("/user/favlist-contents", json={})
    both = client.post(
        "/user/favlist-contents",
        json={"favlist_url_token": 1, "favlist_id": 2},
    )
    non_positive = client.post(
        "/user/favlist-contents",
        json={"favlist_url_token": 0},
    )

    assert missing.status_code == 422
    assert both.status_code == 422
    assert non_positive.status_code == 422


def test_configured_oauth_user_requires_server_token(monkeypatch) -> None:
    monkeypatch.delenv(openwebui.OAUTH_TOKEN_ENV, raising=False)
    client = _client(api_key=None)
    with patch.object(openwebui, "_get_client", return_value=object()):
        response = client.post(
            "/user/contents",
            json={"use_configured_oauth_user": True},
        )
    assert response.status_code == 400
    assert openwebui.OAUTH_TOKEN_ENV in response.json()["detail"]


def test_ppt_pages_are_validated_before_upstream_call() -> None:
    client = _client(api_key=None)
    response = client.post(
        "/ppt/create",
        json={"resource_url": "https://www.zhihu.com/answer/1", "num_pages": 5},
    )
    assert response.status_code == 422
