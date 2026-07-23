"""FastMCP 服务器：暴露知乎搜索、用户数据与异步任务工具。

工具映射：
    search   → 知乎搜索 (scope=zhihu) 或 全网搜索 (scope=web)
    ask      → 直答（OpenAI 兼容 chat completions）
    trending → 热榜
    user_*   → 用户公开内容、关注与收藏
    pdf_*    → PDF 解析任务创建/查询（上传留在本机 CLI）
    ppt_*    → PPT 生成任务创建/查询
    other    → 按当前会话展开、收起或重置上述低频工具

每次返回的内容末尾会附加一行当日配额进度，让 agent / 用户随时看到
还能调用多少次。

本模块只做「MCP 协议适配」一件事；业务逻辑在 commands.py，格式化在 formatters.py。
"""

from __future__ import annotations

import asyncio
import os
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from pydantic import Field

from . import commands, credentials, formatters
from .quota import QuotaTracker
from .upstream.base import McpError
from .upstream.http_client import ZhihuRestClient


mcp = FastMCP("zhihu-search")

# 单例客户端；进程内只创建一次。
_client: ZhihuRestClient | None = None

CORE_MCP_TOOL_NAMES = frozenset({"search", "ask", "trending", "other"})
OPTIONAL_MCP_TOOL_NAMES = frozenset(
    {
        "user_contents",
        "user_followees",
        "user_collections",
        "user_favlists",
        "favlist_contents",
        "pdf_create",
        "pdf_status",
        "ppt_create",
        "ppt_status",
    }
)
ALL_MCP_TOOL_NAMES = CORE_MCP_TOOL_NAMES | OPTIONAL_MCP_TOOL_NAMES
MCP_TOOL_PROFILES = {
    "compact": CORE_MCP_TOOL_NAMES,
    "full": ALL_MCP_TOOL_NAMES,
}
_session_expandable_tool_names = OPTIONAL_MCP_TOOL_NAMES

PaginationOffset = (
    Annotated[int, Field(ge=0)]
    | Annotated[str, Field(min_length=1)]
)


def _effective_mcp_tool_selection(selection: str | None) -> str:
    return (
        selection
        if selection is not None
        else os.environ.get("ZHIHU_MCP_TOOLS", "compact")
    )


def resolve_mcp_tool_names(selection: str | None = None) -> frozenset[str]:
    """Resolve a profile or strict comma-separated allowlist.

    An explicit CLI selection wins over ``ZHIHU_MCP_TOOLS``. The compact
    profile is the safe default because it keeps MCP discovery small while the
    ``other`` tool can reveal low-frequency operations per session.
    """
    value = _effective_mcp_tool_selection(selection)
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("MCP 工具选择不能为空")
    if normalized in MCP_TOOL_PROFILES:
        return MCP_TOOL_PROFILES[normalized]

    names = frozenset(part.strip() for part in normalized.split(",") if part.strip())
    if not names:
        raise ValueError("MCP 工具选择不能为空")
    unknown = names - ALL_MCP_TOOL_NAMES
    if unknown:
        supported = ", ".join(sorted(ALL_MCP_TOOL_NAMES))
        invalid = ", ".join(sorted(unknown))
        raise ValueError(f"未知 MCP 工具：{invalid}；可用工具：{supported}")
    return names


def configure_mcp_tools(selection: str | None = None) -> frozenset[str]:
    """Apply one process-wide MCP tool allowlist before the server starts."""
    global _session_expandable_tool_names

    value = _effective_mcp_tool_selection(selection)
    names = resolve_mcp_tool_names(value)
    if value.strip().lower() in MCP_TOOL_PROFILES:
        _session_expandable_tool_names = OPTIONAL_MCP_TOOL_NAMES
    else:
        _session_expandable_tool_names = names & OPTIONAL_MCP_TOOL_NAMES
    mcp.enable(names=set(names), components={"tool"}, only=True)
    return names


def _oauth_token_from_env(use_configured_user: bool) -> str | None:
    """Resolve a server-side user token without exposing the credential."""
    if not use_configured_user:
        return None
    token = os.environ.get("ZHIHU_OAUTH_TOKEN")
    if not token:
        raise ValueError("ZHIHU_OAUTH_TOKEN 未配置")
    return token


def _get_client() -> ZhihuRestClient:
    """懒加载客户端。第一次调用时读取凭证。"""
    global _client
    if _client is None:
        creds = credentials.load()
        _client = ZhihuRestClient(creds.access_secret)
    return _client


async def aclose_all() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ----------------------------------------------------------------------
# 响应装配
# ----------------------------------------------------------------------


def _ok(
    text: str,
    quota: commands.CommandResult | QuotaTracker | None = None,
) -> ToolResult:
    """正常返回：业务文本 + 配额提示。"""
    body = text.rstrip()
    if body:
        body += "\n\n"
    if isinstance(quota, commands.CommandResult) and quota.quota is not None:
        body += quota.quota.to_line()
    elif isinstance(quota, QuotaTracker):
        body += quota.snapshot().to_line()
    return ToolResult(content=body, is_error=False)


def _err(
    message: str,
    quota: commands.CommandResult | None = None,
) -> ToolResult:
    """错误返回：错误文本 + 配额提示（如果能拿到）。"""
    text = f"[错误] {message}"
    if quota is not None and quota.quota is not None:
        text += f"\n\n{quota.quota.to_line()}"
    return ToolResult(content=text, is_error=True)


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------


@mcp.tool(
    name="search",
    description=(
        "搜索知乎内容。scope='zhihu' 走知乎站内搜索（问题、回答、文章、用户），"
        "scope='web' 走全网搜索（知乎引擎索引的外部网页，可选 filter 表达式）。"
        "返回结构化结果（标题、链接、作者、赞同数、摘要等）。"
    ),
)
async def search(
    query: Annotated[
        str,
        Field(min_length=2, max_length=100, description="搜索关键词。"),
    ],
    scope: Literal["zhihu", "web"] = "zhihu",
    count: Annotated[int, Field(ge=1, le=20, description="返回条数。")] = 10,
    filter: Annotated[
        str,
        Field(description="全网搜索筛选表达式；站内搜索忽略。"),
    ] = "",
    search_db: Literal["all", "realtime", "static"] = "all",
) -> ToolResult:
    """搜索知乎内容。

    Args:
        query: 搜索关键词，2-100 字符。
        scope: 'zhihu' 站内 / 'web' 全网。
        count: 返回条数（zhihu 1-10，web 1-20，默认 10）。
        filter: 高级筛选表达式，仅 scope='web' 生效，例如
            ``host=="example.com" AND publish_time>=1778494631``。
        search_db: 全网搜索索引范围（all / realtime / static）。
    """
    try:
        client = _get_client()
    except credentials.CredentialsError as e:
        return _err(str(e))
    result = await commands.run_search(
        query=query, scope=scope, count=count, filter=filter, search_db=search_db,
        client=client,
    )
    if not result.success:
        return _err(result.error or "未知错误", result)
    return _ok(formatters.format_search_items(result.data, scope), result)


@mcp.tool(
    name="ask",
    description=(
        "调用知乎直答（OpenAI 兼容 chat completions）。"
        "model 取值：'fast' = zhida-fast-1p5（默认，快速）、"
        "'thinking' = zhida-thinking-1p5（深度思考）、"
        "'agent' = zhida-agent（可能耗时 30s 以上，会搜索/调用工具）。"
        "一般情况用 fast 即可。"
    ),
)
async def ask(
    query: Annotated[str, Field(min_length=1, description="问题内容。")],
    model: Literal["fast", "thinking", "agent"] = "fast",
) -> ToolResult:
    """调用知乎直答回答问题。

    Args:
        query: 用户问题（中文或英文均可）。
        model: 模型档位（fast / thinking / agent）。
    """
    try:
        client = _get_client()
    except credentials.CredentialsError as e:
        return _err(str(e))
    result = await commands.run_ask(
        query=query, model=model,
        client=client,
    )
    if not result.success:
        return _err(result.error or "未知错误", result)
    return _ok(formatters.format_zhida_answer(result.data), result)


@mcp.tool(
    name="trending",
    description=(
        "获取当前知乎热榜。返回结构化的标题、链接、缩略图与摘要列表。"
    ),
)
async def trending(
    limit: Annotated[int, Field(ge=1, le=30, description="热榜条数。")] = 30,
) -> ToolResult:
    """获取知乎热榜。

    Args:
        limit: 返回条数 1-30，默认 30。
    """
    try:
        client = _get_client()
    except credentials.CredentialsError as e:
        return _err(str(e))
    result = await commands.run_trending(
        limit=limit,
        client=client,
    )
    if not result.success:
        return _err(result.error or "未知错误", result)
    return _ok(formatters.format_hot_items(result.data), result)


@mcp.tool(
    name="user_contents",
    description=(
        "获取知乎用户公开创作内容。默认查询调用方本人；设置"
        " use_configured_oauth_user=true 时使用服务端 ZHIHU_OAUTH_TOKEN。"
        "支持 Paging.NextOffset 翻页。"
    ),
)
async def user_contents(
    content_type: Annotated[
        Literal["all", "answer", "article", "zvideo", "pin", "question"],
        Field(description="内容类型。"),
    ] = "all",
    offset: Annotated[
        PaginationOffset,
        Field(description="分页偏移，可直接传 Paging.NextOffset。"),
    ] = 0,
    limit: Annotated[int, Field(ge=1, le=50, description="返回数量。")] = 20,
    sort_field: Literal["like_count", "ts"] = "ts",
    sort_order: Literal["asc", "desc"] = "desc",
    use_configured_oauth_user: Annotated[
        bool,
        Field(
            description=(
                "true 使用服务端 ZHIHU_OAUTH_TOKEN；false 查询调用方本人。"
            )
        ),
    ] = False,
) -> ToolResult:
    try:
        client = _get_client()
        oauth_token = _oauth_token_from_env(use_configured_oauth_user)
    except (credentials.CredentialsError, ValueError) as e:
        return _err(str(e))
    result = await commands.run_user_contents(
        content_type=content_type,
        offset=offset,
        limit=limit,
        sort_field=sort_field,
        sort_order=sort_order,
        oauth_token=oauth_token,
        client=client,
    )
    if not result.success:
        return _err(result.error or "未知错误", result)
    return _ok(
        formatters.format_content_items(result.data, heading="知乎用户内容"),
        result,
    )


@mcp.tool(
    name="user_followees",
    description="获取知乎用户公开关注列表；可用 Paging.NextOffset 翻页。",
)
async def user_followees(
    offset: Annotated[
        PaginationOffset,
        Field(description="分页偏移，可直接传 Paging.NextOffset。"),
    ] = 0,
    limit: Annotated[int, Field(ge=1, le=50, description="返回数量。")] = 20,
    use_configured_oauth_user: Annotated[
        bool,
        Field(description="true 使用服务端 ZHIHU_OAUTH_TOKEN。"),
    ] = False,
) -> ToolResult:
    try:
        client = _get_client()
        oauth_token = _oauth_token_from_env(use_configured_oauth_user)
    except (credentials.CredentialsError, ValueError) as e:
        return _err(str(e))
    result = await commands.run_user_followees(
        offset=offset,
        limit=limit,
        oauth_token=oauth_token,
        client=client,
    )
    if not result.success:
        return _err(result.error or "未知错误", result)
    return _ok(formatters.format_followees(result.data), result)


@mcp.tool(
    name="user_collections",
    description="获取知乎用户近期公开收藏；官方接口只提供 limit，不保证完整分页。",
)
async def user_collections(
    limit: Annotated[
        int,
        Field(ge=1, description="返回数量；官方未公布最大值。"),
    ] = 20,
    use_configured_oauth_user: Annotated[
        bool,
        Field(description="true 使用服务端 ZHIHU_OAUTH_TOKEN。"),
    ] = False,
) -> ToolResult:
    try:
        client = _get_client()
        oauth_token = _oauth_token_from_env(use_configured_oauth_user)
    except (credentials.CredentialsError, ValueError) as e:
        return _err(str(e))
    result = await commands.run_user_collections(
        limit=limit,
        oauth_token=oauth_token,
        client=client,
    )
    if not result.success:
        return _err(result.error or "未知错误", result)
    return _ok(
        formatters.format_content_items(result.data, heading="知乎近期收藏"),
        result,
    )


@mcp.tool(
    name="user_favlists",
    description="获取知乎用户收藏夹列表；返回 UrlToken 可用于 favlist_contents。",
)
async def user_favlists(
    limit: Annotated[
        int,
        Field(ge=1, description="返回数量；官方未公布最大值。"),
    ] = 20,
    use_configured_oauth_user: Annotated[
        bool,
        Field(description="true 使用服务端 ZHIHU_OAUTH_TOKEN。"),
    ] = False,
) -> ToolResult:
    try:
        client = _get_client()
        oauth_token = _oauth_token_from_env(use_configured_oauth_user)
    except (credentials.CredentialsError, ValueError) as e:
        return _err(str(e))
    result = await commands.run_user_favlists(
        limit=limit,
        oauth_token=oauth_token,
        client=client,
    )
    if not result.success:
        return _err(result.error or "未知错误", result)
    return _ok(formatters.format_favlists(result.data), result)


@mcp.tool(
    name="favlist_contents",
    description=(
        "获取指定收藏夹的公开内容。favlist_url_token 与 favlist_id 必须二选一，"
        "优先使用 user_favlists 返回的 UrlToken。"
    ),
)
async def favlist_contents(
    favlist_url_token: Annotated[
        int | None,
        Field(ge=1, description="收藏夹 UrlToken；与 favlist_id 二选一。"),
    ] = None,
    favlist_id: Annotated[
        int | None,
        Field(ge=1, description="收藏夹 ID；与 favlist_url_token 二选一。"),
    ] = None,
    offset: Annotated[
        PaginationOffset,
        Field(description="分页偏移，可直接传 Paging.NextOffset。"),
    ] = 0,
    limit: Annotated[
        int,
        Field(ge=1, description="返回数量；官方未公布最大值。"),
    ] = 20,
    use_configured_oauth_user: Annotated[
        bool,
        Field(description="true 使用服务端 ZHIHU_OAUTH_TOKEN。"),
    ] = False,
) -> ToolResult:
    try:
        client = _get_client()
        oauth_token = _oauth_token_from_env(use_configured_oauth_user)
    except (credentials.CredentialsError, ValueError) as e:
        return _err(str(e))
    result = await commands.run_favlist_contents(
        favlist_url_token=favlist_url_token,
        favlist_id=favlist_id,
        offset=offset,
        limit=limit,
        oauth_token=oauth_token,
        client=client,
    )
    if not result.success:
        return _err(result.error or "未知错误", result)
    return _ok(
        formatters.format_content_items(result.data, heading="知乎收藏夹内容"),
        result,
    )


@mcp.tool(
    name="pdf_create",
    description=(
        "使用已上传的 file_id 创建 PDF 解析任务。文件上传需先在运行服务的"
        "机器上执行 zhihu-search pdf-upload，避免远程工具读取任意本地文件。"
    ),
)
async def pdf_create(
    file_id: Annotated[
        str,
        Field(min_length=1, description="pdf-upload 返回的 file_id。"),
    ],
    idempotency_key: Annotated[
        str,
        Field(description="可选幂等键；同一键不可用于不同参数。"),
    ] = "",
) -> ToolResult:
    try:
        client = _get_client()
    except credentials.CredentialsError as e:
        return _err(str(e))
    result = await commands.run_pdf_create(
        file_id=file_id,
        idempotency_key=idempotency_key or None,
        client=client,
    )
    if not result.success:
        return _err(result.error or "未知错误", result)
    return _ok(formatters.format_task_status(result.data, "PDF"), result)


@mcp.tool(
    name="pdf_status",
    description="查询 PDF 解析任务状态；成功后 result.url 是短期有效的 JSON 下载链接。",
)
async def pdf_status(
    task_id: Annotated[
        str,
        Field(
            pattern=r"^pdf_[A-Za-z0-9_-]+$",
            description="PDF 解析任务 ID。",
        ),
    ],
) -> ToolResult:
    try:
        client = _get_client()
    except credentials.CredentialsError as e:
        return _err(str(e))
    result = await commands.run_pdf_status(task_id=task_id, client=client)
    if not result.success:
        return _err(result.error or "未知错误", result)
    return _ok(formatters.format_task_status(result.data, "PDF"), result)


@mcp.tool(
    name="ppt_create",
    description="根据知乎回答或专栏文章链接创建 6-21 页的 PPT 生成任务。",
)
async def ppt_create(
    resource_url: Annotated[
        str,
        Field(min_length=1, description="知乎回答或专栏文章 HTTPS 链接。"),
    ],
    num_pages: Annotated[
        int,
        Field(ge=6, le=21, description="生成页数。"),
    ] = 12,
    idempotency_key: Annotated[
        str,
        Field(description="可选幂等键；同一键不可用于不同参数。"),
    ] = "",
) -> ToolResult:
    try:
        client = _get_client()
    except credentials.CredentialsError as e:
        return _err(str(e))
    result = await commands.run_ppt_create(
        resource_url=resource_url,
        num_pages=num_pages,
        idempotency_key=idempotency_key or None,
        client=client,
    )
    if not result.success:
        return _err(result.error or "未知错误", result)
    return _ok(formatters.format_task_status(result.data, "PPT"), result)


@mcp.tool(
    name="ppt_status",
    description="查询 PPT 生成任务状态；成功后 result.url 是短期有效的 PPTX 下载链接。",
)
async def ppt_status(
    task_id: Annotated[
        str,
        Field(
            pattern=r"^ppt_[A-Za-z0-9_-]+$",
            description="PPT 生成任务 ID。",
        ),
    ],
) -> ToolResult:
    try:
        client = _get_client()
    except credentials.CredentialsError as e:
        return _err(str(e))
    result = await commands.run_ppt_status(task_id=task_id, client=client)
    if not result.success:
        return _err(result.error or "未知错误", result)
    return _ok(formatters.format_task_status(result.data, "PPT"), result)


@mcp.tool(
    name="other",
    title="其他",
    description=(
        "按当前 MCP 会话展开或收起低频工具。action='enable' 展开用户数据、"
        "PDF 和 PPT 工具；'disable' 收起；'reset' 恢复服务器启动配置。"
    ),
)
async def other(
    ctx: Context,
    action: Literal["enable", "disable", "reset"] = "enable",
) -> ToolResult:
    """Manage low-frequency tools for the current MCP session only."""
    optional = set(_session_expandable_tool_names)
    if action == "enable":
        if not optional:
            return _ok(
                "当前自定义 MCP allowlist 没有包含低频工具，因此没有可展开项。"
            )
        await ctx.enable_components(names=optional, components={"tool"})
        enabled = "、".join(sorted(optional))
        return _ok(
            f"已展开其他工具：{enabled}\n"
            "工具列表已更新，可按名称调用；用 other(action='disable') 收起。"
        )
    if action == "disable":
        if not optional:
            return _ok(
                "当前自定义 MCP allowlist 没有包含低频工具，因此无需收起。"
            )
        await ctx.disable_components(names=optional, components={"tool"})
        return _ok(
            f"已收起 {len(optional)} 个低频工具；其他已允许的工具保持可用。"
        )

    await ctx.reset_visibility()
    return _ok("已恢复服务器启动时的 MCP 工具配置。")


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------

# Keep direct ``zhihu_search.server:mcp`` imports aligned with the documented
# default. ``main`` applies the explicit CLI/environment selection afterward.
configure_mcp_tools("compact")


def main(tool_selection: str | None = None) -> None:
    """以 stdio 模式启动 MCP 服务器。"""
    configure_mcp_tools(tool_selection)
    try:
        mcp.run(transport="stdio")
    finally:
        # mcp.run() 内部由 anyio 管理事件循环；进程退出前关闭全局客户端。
        try:
            asyncio.run(aclose_all())
        except Exception:  # pragma: no cover - 清理失败不应影响退出码
            pass


if __name__ == "__main__":
    main()
