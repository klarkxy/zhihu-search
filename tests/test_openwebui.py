"""openwebui.py 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from zhihu_search import openwebui
from zhihu_search.commands import CommandResult


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
