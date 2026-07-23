"""共用业务层：CLI 与 MCP 都通过此模块调用知乎 API。

每个函数封装了凭证加载 → 熔断检查 → 客户端创建 → API 调用 → 错误翻译全流程：
返回 ``CommandResult``，调用方再决定如何输出（markdown、json 或 MCP 响应）。

使用方式（CLI）：
    from zhihu_search import commands
    result = await commands.run_search("RAG")
    if result.success:
        print(result.data)

使用方式（MCP — 复用现有客户端）：
    result = await commands.run_search("RAG", client=mcp_client)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from . import credentials
from .quota import QuotaKind, QuotaSnapshot, QuotaTracker
from .upstream.base import McpError, RateLimited
from .upstream.http_client import ApiResult, ZhihuRestClient


@dataclass
class CommandResult:
    """一次命令调用的完整结果。"""

    success: bool
    data: Any | None = None
    quota: Optional[QuotaSnapshot] = None
    error: Optional[str] = None
    #: 原始响应 headers（诊断用）
    headers: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _make_client(client: ZhihuRestClient | None) -> tuple[ZhihuRestClient, bool]:
    """如果未提供 client，创建一个新的；返回 (client, owns_client)。"""
    if client is not None:
        return client, False
    try:
        creds = credentials.load()
    except credentials.CredentialsError:
        raise
    return ZhihuRestClient(creds.access_secret), True


async def _try_close(client: ZhihuRestClient, owns: bool) -> None:
    """如果 client 是自建的，释放它。"""
    if owns:
        try:
            await client.aclose()
        except Exception:
            pass


def _breaker_open_msg(kind: QuotaKind, tracker: QuotaTracker) -> str:
    """组装熔断消息。"""
    info = tracker.breaker_info(kind)
    secs = int(info.remaining_cooldown)
    label = {
        "search": "搜索",
        "trending": "热榜",
        "ask": "直答",
        "user": "用户",
        "pdf": "PDF",
        "ppt": "PPT",
    }.get(kind, kind)
    return f"{label}接口已被熔断，剩余冷却约 {secs} 秒，请稍后重试。"


def _kind_for_scope(scope: str) -> QuotaKind:
    """``scope`` 参数映射到配额类别。搜索和全网搜索都走 ``search`` 桶。"""
    return "search"


_CommandCall = Callable[[ZhihuRestClient], Awaitable[ApiResult]]


async def _run_command(
    kind: QuotaKind,
    call: _CommandCall,
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """运行一个已绑定参数的客户端调用，并统一处理配额、错误和资源释放。"""
    own, owns = _make_client(client)
    tracker = own.quota_tracker

    try:
        if not tracker.is_allowed(kind):
            return CommandResult(
                success=False,
                error=_breaker_open_msg(kind, tracker),
                quota=tracker.snapshot(),
            )

        result = await call(own)
        tracker.record_success(kind)
        return CommandResult(
            success=True,
            data=result.data,
            quota=result.quota,
            headers=result.headers,
        )
    except RateLimited as exc:
        tracker.record_failure(kind)
        return CommandResult(
            success=False,
            error=str(exc),
            quota=tracker.snapshot(),
        )
    except McpError as exc:
        return CommandResult(
            success=False,
            error=str(exc),
            quota=tracker.snapshot(),
        )
    except Exception as exc:
        return CommandResult(success=False, error=f"未预期错误：{exc}")
    finally:
        await _try_close(own, owns)


# ---------------------------------------------------------------------------
# 直答模型映射
# ---------------------------------------------------------------------------

_MODEL_MAP: dict[str, str] = {
    "fast": "zhida-fast-1p5",
    "thinking": "zhida-thinking-1p5",
    "agent": "zhida-agent",
}


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------


async def run_search(
    query: str,
    scope: str = "zhihu",
    count: int = 10,
    filter: str = "",
    search_db: str = "all",
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """搜索知乎内容。

    Args:
        query: 搜索关键词。
        scope: ``zhihu``（站内）或 ``web``（全网）。
        count: 返回条数。
        filter: 高级筛选，仅 ``scope='web'`` 生效。
        search_db: 全网搜索索引范围（``all`` / ``realtime`` / ``static``）。
        client: 可复用的客户端实例（MCP 场景传入）。

    Returns:
        :class:`CommandResult`，success 为 True 时 data 含 API 响应体。
    """
    async def call(own: ZhihuRestClient) -> ApiResult:
        if scope == "zhihu":
            return await own.zhihu_search(query=query, count=count)
        return await own.global_search(
            query=query,
            count=count,
            filter=filter,
            search_db=search_db,
        )

    return await _run_command(_kind_for_scope(scope), call, client)


async def run_ask(
    query: str,
    model: str = "fast",
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """调用知乎直答。

    Args:
        query: 问题。
        model: ``fast`` / ``thinking`` / ``agent``。
        client: 可复用的客户端实例。

    Returns:
        :class:`CommandResult`，data 含 ``content``、``reasoning_content`` 等字段。
    """
    mapped = _MODEL_MAP.get(model, "zhida-fast-1p5")
    return await _run_command(
        "ask",
        lambda own: own.zhida(query=query, model=mapped),
        client,
    )


async def run_trending(
    limit: int = 30,
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """获取知乎热榜。

    Args:
        limit: 返回条数。
        client: 可复用的客户端实例。

    Returns:
        :class:`CommandResult`，data 含 ``Items`` 列表。
    """
    return await _run_command(
        "trending",
        lambda own: own.hot_list(limit=limit),
        client,
    )


async def run_user_contents(
    content_type: str = "all",
    offset: int | str = 0,
    limit: int = 20,
    sort_field: str = "ts",
    sort_order: str = "desc",
    oauth_token: str | None = None,
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """获取当前授权用户的内容列表。"""
    return await _run_command(
        "user",
        lambda own: own.user_contents(
            content_type=content_type,
            offset=offset,
            limit=limit,
            sort_field=sort_field,
            sort_order=sort_order,
            oauth_token=oauth_token,
        ),
        client,
    )


async def run_user_followees(
    offset: int | str = 0,
    limit: int = 20,
    oauth_token: str | None = None,
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """获取当前授权用户关注的人。"""
    return await _run_command(
        "user",
        lambda own: own.user_followees(
            offset=offset,
            limit=limit,
            oauth_token=oauth_token,
        ),
        client,
    )


async def run_user_collections(
    limit: int = 20,
    oauth_token: str | None = None,
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """获取当前授权用户最近创建的收藏夹。"""
    return await _run_command(
        "user",
        lambda own: own.user_collections(limit=limit, oauth_token=oauth_token),
        client,
    )


async def run_user_favlists(
    limit: int = 20,
    oauth_token: str | None = None,
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """获取当前授权用户最近收藏的收藏夹。"""
    return await _run_command(
        "user",
        lambda own: own.user_favlists(limit=limit, oauth_token=oauth_token),
        client,
    )


async def run_favlist_contents(
    *,
    favlist_url_token: int | None = None,
    favlist_id: int | None = None,
    offset: int | str = 0,
    limit: int = 20,
    oauth_token: str | None = None,
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """获取指定收藏夹的内容。"""
    return await _run_command(
        "user",
        lambda own: own.favlist_contents(
            favlist_url_token=favlist_url_token,
            favlist_id=favlist_id,
            offset=offset,
            limit=limit,
            oauth_token=oauth_token,
        ),
        client,
    )


async def run_pdf_upload(
    file_path: str,
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """上传本地 PDF 文件。"""
    return await _run_command(
        "pdf",
        lambda own: own.upload_pdf(file_path=file_path),
        client,
    )


async def run_pdf_create(
    file_id: str,
    idempotency_key: str | None = None,
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """创建 PDF 解析任务。"""
    return await _run_command(
        "pdf",
        lambda own: own.create_pdf_parse_task(
            file_id=file_id,
            idempotency_key=idempotency_key,
        ),
        client,
    )


async def run_pdf_status(
    task_id: str,
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """查询 PDF 解析任务。"""
    return await _run_command(
        "pdf",
        lambda own: own.get_pdf_parse_task(task_id=task_id),
        client,
    )


async def run_ppt_create(
    resource_url: str,
    num_pages: int = 12,
    idempotency_key: str | None = None,
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """创建 PPT 生成任务。"""
    return await _run_command(
        "ppt",
        lambda own: own.create_ppt_generation_task(
            resource_url=resource_url,
            num_pages=num_pages,
            idempotency_key=idempotency_key,
        ),
        client,
    )


async def run_ppt_status(
    task_id: str,
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """查询 PPT 生成任务。"""
    return await _run_command(
        "ppt",
        lambda own: own.get_ppt_generation_task(task_id=task_id),
        client,
    )
