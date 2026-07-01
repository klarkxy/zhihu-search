"""Open WebUI / OpenAPI tool server.

This module exposes the same three tools as the stdio MCP server, but as a
plain HTTP OpenAPI service that Open WebUI can import directly.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import commands, credentials, formatters
from .quota import QuotaSnapshot
from .upstream.http_client import ZhihuRestClient


API_KEY_ENV = "ZHIHU_OPENWEBUI_API_KEY"

_client: ZhihuRestClient | None = None
_api_key: str | None = None
_bearer = HTTPBearer(
    scheme_name="BearerAuth",
    description="Open WebUI tool-server API key.",
    auto_error=False,
)


class SearchRequest(BaseModel):
    """Search request parameters."""

    query: str = Field(..., min_length=2, max_length=100, description="搜索关键词。")
    scope: Literal["zhihu", "web"] = Field(
        "zhihu",
        description="zhihu 为知乎站内搜索，web 为全网搜索。",
    )
    count: int = Field(10, ge=1, le=20, description="返回条数。zhihu 上限 10，web 上限 20。")
    filter: str = Field(
        "",
        description='仅 scope=web 生效，例如 host=="example.com"。',
    )


class AskRequest(BaseModel):
    """Zhihu Zhida request parameters."""

    query: str = Field(..., min_length=1, description="问题内容。")
    model: Literal["fast", "thinking", "agent"] = Field(
        "fast",
        description="fast 快速，thinking 深度思考，agent 可能耗时更久。",
    )


class TrendingRequest(BaseModel):
    """Trending request parameters."""

    limit: int = Field(30, ge=1, le=30, description="返回热榜条数。")


class ToolResponse(BaseModel):
    """Common response shape for OpenAPI tools."""

    success: bool
    kind: Literal["search", "ask", "trending"]
    content: str = Field(
        "",
        description="Markdown text optimized for the model to read.",
    )
    data: dict | None = Field(None, description="Raw upstream payload.")
    quota: dict | None = Field(None, description="Local quota and circuit-breaker snapshot.")
    error: str | None = Field(None, description="Error message when success is false.")


def _quota_to_dict(snapshot: QuotaSnapshot | None) -> dict | None:
    if snapshot is None:
        return None
    return {
        "by_kind": snapshot.by_kind,
        "reset_at": snapshot.reset_at,
        "breakers": {
            kind: {
                "state": breaker.state,
                "remaining_cooldown": breaker.remaining_cooldown,
            }
            for kind, breaker in (snapshot.breakers or {}).items()
        },
    }


def _with_quota(text: str, result: commands.CommandResult) -> str:
    body = text.rstrip()
    if body:
        body += "\n\n"
    if result.quota is not None:
        body += result.quota.to_line()
    return body


def _response(
    kind: Literal["search", "ask", "trending"],
    result: commands.CommandResult,
    content: str = "",
) -> ToolResponse:
    if not result.success:
        error = result.error or "未知错误"
        body = f"[错误] {error}"
        if result.quota is not None:
            body += f"\n\n{result.quota.to_line()}"
        return ToolResponse(
            success=False,
            kind=kind,
            content=body,
            quota=_quota_to_dict(result.quota),
            error=error,
        )
    return ToolResponse(
        success=True,
        kind=kind,
        content=_with_quota(content, result),
        data=result.data or {},
        quota=_quota_to_dict(result.quota),
    )


def _get_client() -> ZhihuRestClient:
    """Lazily create one reusable upstream client for the HTTP process."""
    global _client
    if _client is None:
        creds = credentials.load()
        _client = ZhihuRestClient(creds.access_secret)
    return _client


async def aclose_all() -> None:
    """Close process-global resources."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _verify_api_key(
    credentials_: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)] = None,
) -> None:
    if not _api_key:
        return
    if credentials_ is None or credentials_.credentials != _api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


def create_app(api_key: str | None = None) -> FastAPI:
    """Create the OpenAPI app.

    Args:
        api_key: Optional bearer token expected on tool endpoints. If omitted,
            ``ZHIHU_OPENWEBUI_API_KEY`` is used. Empty means no auth.
    """
    global _api_key
    _api_key = api_key or os.environ.get(API_KEY_ENV) or None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await aclose_all()

    app = FastAPI(
        title="zhihu-search Open WebUI Tool Server",
        version="1.0.0",
        description=(
            "知乎开放平台 OpenAPI 工具服务器，暴露 search、ask、trending 三个工具。"
        ),
        lifespan=lifespan,
    )

    tool_auth = Depends(_verify_api_key)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/search",
        response_model=ToolResponse,
        dependencies=[tool_auth],
        operation_id="search",
        summary="搜索知乎内容或全网内容",
    )
    async def search(request: SearchRequest) -> ToolResponse:
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return ToolResponse(
                success=False,
                kind="search",
                content=f"[错误] {e}",
                error=str(e),
            )
        result = await commands.run_search(
            query=request.query,
            scope=request.scope,
            count=min(request.count, 10) if request.scope == "zhihu" else request.count,
            filter=request.filter,
            client=client,
        )
        content = formatters.format_search_items(result.data, request.scope) if result.success else ""
        return _response("search", result, content)

    @app.post(
        "/ask",
        response_model=ToolResponse,
        dependencies=[tool_auth],
        operation_id="ask",
        summary="调用知乎直答",
    )
    async def ask(request: AskRequest) -> ToolResponse:
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return ToolResponse(
                success=False,
                kind="ask",
                content=f"[错误] {e}",
                error=str(e),
            )
        result = await commands.run_ask(
            query=request.query,
            model=request.model,
            client=client,
        )
        content = formatters.format_zhida_answer(result.data) if result.success else ""
        return _response("ask", result, content)

    @app.post(
        "/trending",
        response_model=ToolResponse,
        dependencies=[tool_auth],
        operation_id="trending",
        summary="获取当前知乎热榜",
    )
    async def trending(request: TrendingRequest | None = None) -> ToolResponse:
        request = request or TrendingRequest()
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return ToolResponse(
                success=False,
                kind="trending",
                content=f"[错误] {e}",
                error=str(e),
            )
        result = await commands.run_trending(limit=request.limit, client=client)
        content = formatters.format_hot_items(result.data) if result.success else ""
        return _response("trending", result, content)

    return app


def main(host: str = "127.0.0.1", port: int = 8000, api_key: str | None = None) -> None:
    """Run the OpenAPI tool server."""
    import uvicorn

    app = create_app(api_key=api_key)
    try:
        uvicorn.run(app, host=host, port=port)
    finally:
        try:
            asyncio.run(aclose_all())
        except Exception:
            pass


app = create_app()


__all__ = ["API_KEY_ENV", "ToolResponse", "create_app", "main", "app"]
