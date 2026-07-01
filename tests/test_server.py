"""server.py 单元测试：凭证缺失时返回结构化错误。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from zhihu_search import server
from zhihu_search.credentials import CredentialsError


@pytest.fixture(autouse=True)
def reset_client() -> None:
    """每个测试前后清空全局客户端，避免测试间相互影响。"""
    server._client = None
    yield
    server._client = None


def _mock_credentials_error(*args: object, **kwargs: object) -> None:
    raise CredentialsError("未找到知乎 Access Secret")


@pytest.mark.asyncio
async def test_search_returns_structured_error_on_missing_creds() -> None:
    """search 在凭证缺失时返回结构化错误而非抛异常。"""
    with patch.object(server, "_get_client", side_effect=_mock_credentials_error):
        result = await server.search(query="测试")

    assert isinstance(result, dict)
    assert result.get("isError") is True
    content = result.get("content", [])
    assert len(content) > 0
    assert content[0]["type"] == "text"
    assert "未找到" in content[0]["text"]


@pytest.mark.asyncio
async def test_ask_returns_structured_error_on_missing_creds() -> None:
    """ask 在凭证缺失时返回结构化错误。"""
    with patch.object(server, "_get_client", side_effect=_mock_credentials_error):
        result = await server.ask(query="什么是RAG")

    assert isinstance(result, dict)
    assert result.get("isError") is True
    content = result.get("content", [])
    assert len(content) > 0
    assert "未找到" in content[0]["text"]


@pytest.mark.asyncio
async def test_trending_returns_structured_error_on_missing_creds() -> None:
    """trending 在凭证缺失时返回结构化错误。"""
    with patch.object(server, "_get_client", side_effect=_mock_credentials_error):
        result = await server.trending()

    assert isinstance(result, dict)
    assert result.get("isError") is True
    content = result.get("content", [])
    assert len(content) > 0
    assert "未找到" in content[0]["text"]
