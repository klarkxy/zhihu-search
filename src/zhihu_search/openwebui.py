"""Open WebUI / OpenAPI tool server.

This module exposes the model-safe subset of the CLI/MCP operations as a plain
HTTP OpenAPI service that Open WebUI can import directly.

Local PDF file upload and OAuth token exchange are intentionally CLI/Python
only: accepting a server-local path would create a file-read primitive, while
putting an OAuth app key in a model-visible request would leak a secret.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import __version__, commands, credentials, formatters
from .quota import QuotaSnapshot
from .upstream.http_client import ZhihuRestClient


API_KEY_ENV = "ZHIHU_OPENWEBUI_API_KEY"
OAUTH_TOKEN_ENV = "ZHIHU_OAUTH_TOKEN"

_client: ZhihuRestClient | None = None
_bearer = HTTPBearer(
    scheme_name="BearerAuth",
    description="Open WebUI tool-server API key.",
    auto_error=False,
)

PaginationOffset = (
    Annotated[int, Field(ge=0)]
    | Annotated[str, Field(min_length=1)]
)


def _oauth_token_from_env(use_configured_user: bool) -> str | None:
    """Resolve an optional server-side token without exposing it in schemas."""
    if not use_configured_user:
        return None
    token = os.environ.get(OAUTH_TOKEN_ENV)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{OAUTH_TOKEN_ENV} is not configured",
        )
    return token


class ToolRequest(BaseModel):
    """Strict base model so secret-like unknown fields are not ignored."""

    model_config = ConfigDict(extra="forbid")


class UserDataRequest(ToolRequest):
    """Select self data or the one server-configured OAuth user."""

    use_configured_oauth_user: bool = Field(
        False,
        description=(
            "false 查询调用方本人；true 使用服务端 ZHIHU_OAUTH_TOKEN，"
            "不会在工具调用中暴露 token。"
        ),
    )


class SearchRequest(ToolRequest):
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
    search_db: Literal["all", "realtime", "static"] = Field(
        "all",
        description="全网搜索索引范围，仅 scope=web 生效。",
    )


class AskRequest(ToolRequest):
    """Zhihu Zhida request parameters."""

    query: str = Field(..., min_length=1, description="问题内容。")
    model: Literal["fast", "thinking", "agent"] = Field(
        "fast",
        description="fast 快速，thinking 深度思考，agent 可能耗时更久。",
    )


class TrendingRequest(ToolRequest):
    """Trending request parameters."""

    limit: int = Field(30, ge=1, le=30, description="返回热榜条数。")


class UserContentsRequest(UserDataRequest):
    """User-created content request."""

    content_type: Literal[
        "all", "answer", "article", "zvideo", "pin", "question"
    ] = Field("all", description="内容类型。")
    offset: PaginationOffset = Field(
        0,
        description="分页偏移；可直接传上一页 Paging.NextOffset。",
    )
    limit: int = Field(20, ge=1, le=50, description="返回数量，最大 50。")
    sort_field: Literal["like_count", "ts"] = Field("ts", description="排序字段。")
    sort_order: Literal["asc", "desc"] = Field("desc", description="排序方向。")


class UserFolloweesRequest(UserDataRequest):
    """User followee-list request."""

    offset: PaginationOffset = Field(
        0,
        description="分页偏移；可直接传上一页 Paging.NextOffset。",
    )
    limit: int = Field(20, ge=1, le=50, description="返回数量，最大 50。")


class UserLimitRequest(UserDataRequest):
    """Request shared by recent collections and favorite-list listing."""

    limit: int = Field(20, ge=1, description="返回数量；官方未公布最大值。")


class FavlistContentsRequest(UserDataRequest):
    """Favorite-list content request."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "oneOf": [
                {
                    "required": ["favlist_url_token"],
                    "not": {"required": ["favlist_id"]},
                },
                {
                    "required": ["favlist_id"],
                    "not": {"required": ["favlist_url_token"]},
                },
            ]
        },
    )

    favlist_url_token: int | None = Field(
        None,
        ge=1,
        description="收藏夹 URL 标识；与 favlist_id 二选一。",
    )
    favlist_id: int | None = Field(
        None,
        ge=1,
        description="收藏夹 ID；与 favlist_url_token 二选一。",
    )
    offset: PaginationOffset = Field(
        0,
        description="分页偏移；可直接传上一页 Paging.NextOffset。",
    )
    limit: int = Field(20, ge=1, description="返回数量；官方未公布最大值。")

    @model_validator(mode="after")
    def validate_identifier(self) -> "FavlistContentsRequest":
        supplied = (
            self.favlist_url_token is not None,
            self.favlist_id is not None,
        )
        if sum(supplied) != 1:
            raise ValueError("favlist_url_token 与 favlist_id 必须且只能提供一个")
        return self


class PdfCreateRequest(ToolRequest):
    """PDF parse-task creation request."""

    file_id: str = Field(..., min_length=1, description="PDF 上传接口返回的 file_id。")
    idempotency_key: str = Field("", description="可选幂等键。")


class PdfStatusRequest(ToolRequest):
    """PDF parse-task status request."""

    task_id: str = Field(
        ...,
        pattern=r"^pdf_[A-Za-z0-9_-]+$",
        description="PDF 解析任务 ID。",
    )


class PptStatusRequest(ToolRequest):
    """PPT generation-task status request."""

    task_id: str = Field(
        ...,
        pattern=r"^ppt_[A-Za-z0-9_-]+$",
        description="PPT 生成任务 ID。",
    )


class PptCreateRequest(ToolRequest):
    """PPT generation-task creation request."""

    resource_url: str = Field(..., min_length=1, description="知乎回答或文章链接。")
    num_pages: int = Field(12, ge=6, le=21, description="生成页数，范围 6-21。")
    idempotency_key: str = Field("", description="可选幂等键。")


class ToolResponse(BaseModel):
    """Common response shape for OpenAPI tools."""

    success: bool
    kind: str
    content: str = Field(
        "",
        description="Markdown text optimized for the model to read.",
    )
    data: Any | None = Field(None, description="Raw upstream payload.")
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
    kind: str,
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
        data=result.data if result.data is not None else {},
        quota=_quota_to_dict(result.quota),
    )


def _credentials_error(kind: str, error: credentials.CredentialsError) -> ToolResponse:
    """Turn a missing/invalid Access Secret into the common tool response."""
    message = str(error)
    return ToolResponse(
        success=False,
        kind=kind,
        content=f"[错误] {message}",
        error=message,
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


def create_app(api_key: str | None = None) -> FastAPI:
    """Create the OpenAPI app.

    Args:
        api_key: Optional bearer token expected on tool endpoints. If omitted,
            ``ZHIHU_OPENWEBUI_API_KEY`` is used. Empty means no auth.
    """
    resolved_api_key = (
        os.environ.get(API_KEY_ENV) or None
        if api_key is None
        else api_key or None
    )

    async def verify_api_key(
        credentials_: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(_bearer),
        ] = None,
    ) -> None:
        """Per-app verifier: one app cannot disable another app's key."""
        if credentials_ is None or credentials_.credentials != resolved_api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await aclose_all()

    app = FastAPI(
        title="zhihu-search Open WebUI Tool Server",
        version=__version__,
        description=(
            "知乎开放平台 OpenAPI 工具服务器，提供搜索、直答、热榜、"
            "用户公开数据以及 PDF/PPT 异步任务操作。"
        ),
        lifespan=lifespan,
    )

    auth_dependencies = [Depends(verify_api_key)] if resolved_api_key else []
    tool_router = APIRouter(dependencies=auth_dependencies)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @tool_router.post(
        "/search",
        response_model=ToolResponse,
        operation_id="search",
        summary="搜索知乎内容或全网内容",
    )
    async def search(request: SearchRequest) -> ToolResponse:
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return _credentials_error("search", e)
        result = await commands.run_search(
            query=request.query,
            scope=request.scope,
            count=min(request.count, 10) if request.scope == "zhihu" else request.count,
            filter=request.filter,
            search_db=request.search_db,
            client=client,
        )
        content = formatters.format_search_items(result.data, request.scope) if result.success else ""
        return _response("search", result, content)

    @tool_router.post(
        "/ask",
        response_model=ToolResponse,
        operation_id="ask",
        summary="调用知乎直答",
    )
    async def ask(request: AskRequest) -> ToolResponse:
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return _credentials_error("ask", e)
        result = await commands.run_ask(
            query=request.query,
            model=request.model,
            client=client,
        )
        content = formatters.format_zhida_answer(result.data) if result.success else ""
        return _response("ask", result, content)

    @tool_router.post(
        "/trending",
        response_model=ToolResponse,
        operation_id="trending",
        summary="获取当前知乎热榜",
    )
    async def trending(request: TrendingRequest | None = None) -> ToolResponse:
        request = request or TrendingRequest()
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return _credentials_error("trending", e)
        result = await commands.run_trending(limit=request.limit, client=client)
        content = formatters.format_hot_items(result.data) if result.success else ""
        return _response("trending", result, content)

    @tool_router.post(
        "/user/contents",
        response_model=ToolResponse,
        operation_id="user_contents",
        summary="获取知乎用户公开创作内容",
    )
    async def user_contents(request: UserContentsRequest) -> ToolResponse:
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return _credentials_error("user_contents", e)
        result = await commands.run_user_contents(
            content_type=request.content_type,
            offset=request.offset,
            limit=request.limit,
            sort_field=request.sort_field,
            sort_order=request.sort_order,
            oauth_token=_oauth_token_from_env(
                request.use_configured_oauth_user
            ),
            client=client,
        )
        content = (
            formatters.format_content_items(result.data, heading="知乎用户内容")
            if result.success
            else ""
        )
        return _response("user_contents", result, content)

    @tool_router.post(
        "/user/followees",
        response_model=ToolResponse,
        operation_id="user_followees",
        summary="获取知乎用户公开关注列表",
    )
    async def user_followees(request: UserFolloweesRequest) -> ToolResponse:
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return _credentials_error("user_followees", e)
        result = await commands.run_user_followees(
            offset=request.offset,
            limit=request.limit,
            oauth_token=_oauth_token_from_env(
                request.use_configured_oauth_user
            ),
            client=client,
        )
        content = formatters.format_followees(result.data) if result.success else ""
        return _response("user_followees", result, content)

    @tool_router.post(
        "/user/collections",
        response_model=ToolResponse,
        operation_id="user_collections",
        summary="获取知乎用户近期公开收藏",
    )
    async def user_collections(request: UserLimitRequest) -> ToolResponse:
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return _credentials_error("user_collections", e)
        result = await commands.run_user_collections(
            limit=request.limit,
            oauth_token=_oauth_token_from_env(
                request.use_configured_oauth_user
            ),
            client=client,
        )
        content = (
            formatters.format_content_items(result.data, heading="知乎近期收藏")
            if result.success
            else ""
        )
        return _response("user_collections", result, content)

    @tool_router.post(
        "/user/favlists",
        response_model=ToolResponse,
        operation_id="user_favlists",
        summary="获取知乎用户收藏夹列表",
    )
    async def user_favlists(request: UserLimitRequest) -> ToolResponse:
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return _credentials_error("user_favlists", e)
        result = await commands.run_user_favlists(
            limit=request.limit,
            oauth_token=_oauth_token_from_env(
                request.use_configured_oauth_user
            ),
            client=client,
        )
        content = formatters.format_favlists(result.data) if result.success else ""
        return _response("user_favlists", result, content)

    @tool_router.post(
        "/user/favlist-contents",
        response_model=ToolResponse,
        operation_id="favlist_contents",
        summary="获取指定知乎收藏夹的公开内容",
    )
    async def favlist_contents(request: FavlistContentsRequest) -> ToolResponse:
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return _credentials_error("favlist_contents", e)
        result = await commands.run_favlist_contents(
            favlist_url_token=request.favlist_url_token,
            favlist_id=request.favlist_id,
            offset=request.offset,
            limit=request.limit,
            oauth_token=_oauth_token_from_env(
                request.use_configured_oauth_user
            ),
            client=client,
        )
        content = (
            formatters.format_content_items(result.data, heading="知乎收藏夹内容")
            if result.success
            else ""
        )
        return _response("favlist_contents", result, content)

    @tool_router.post(
        "/pdf/create",
        response_model=ToolResponse,
        operation_id="pdf_create",
        summary="使用已上传的 file_id 创建 PDF 解析任务",
    )
    async def pdf_create(request: PdfCreateRequest) -> ToolResponse:
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return _credentials_error("pdf_create", e)
        result = await commands.run_pdf_create(
            file_id=request.file_id,
            idempotency_key=request.idempotency_key or None,
            client=client,
        )
        content = (
            formatters.format_task_status(result.data, "PDF")
            if result.success
            else ""
        )
        return _response("pdf_create", result, content)

    @tool_router.post(
        "/pdf/status",
        response_model=ToolResponse,
        operation_id="pdf_status",
        summary="查询 PDF 解析任务状态",
    )
    async def pdf_status(request: PdfStatusRequest) -> ToolResponse:
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return _credentials_error("pdf_status", e)
        result = await commands.run_pdf_status(task_id=request.task_id, client=client)
        content = (
            formatters.format_task_status(result.data, "PDF")
            if result.success
            else ""
        )
        return _response("pdf_status", result, content)

    @tool_router.post(
        "/ppt/create",
        response_model=ToolResponse,
        operation_id="ppt_create",
        summary="根据知乎回答或文章创建 PPT 生成任务",
    )
    async def ppt_create(request: PptCreateRequest) -> ToolResponse:
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return _credentials_error("ppt_create", e)
        result = await commands.run_ppt_create(
            resource_url=request.resource_url,
            num_pages=request.num_pages,
            idempotency_key=request.idempotency_key or None,
            client=client,
        )
        content = (
            formatters.format_task_status(result.data, "PPT")
            if result.success
            else ""
        )
        return _response("ppt_create", result, content)

    @tool_router.post(
        "/ppt/status",
        response_model=ToolResponse,
        operation_id="ppt_status",
        summary="查询 PPT 生成任务状态",
    )
    async def ppt_status(request: PptStatusRequest) -> ToolResponse:
        try:
            client = _get_client()
        except credentials.CredentialsError as e:
            return _credentials_error("ppt_status", e)
        result = await commands.run_ppt_status(task_id=request.task_id, client=client)
        content = (
            formatters.format_task_status(result.data, "PPT")
            if result.success
            else ""
        )
        return _response("ppt_status", result, content)

    app.include_router(tool_router)
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
