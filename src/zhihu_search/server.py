"""FastMCP 服务器：暴露 3 个工具，背后转发到 4 个知乎开放平台 REST 接口。

工具映射：
    search   → 知乎搜索 (scope=zhihu) 或 全网搜索 (scope=web)
    ask      → 直答（OpenAI 兼容 chat completions）
    trending → 热榜

每次返回的内容末尾会附加一行当日配额进度，让 agent / 用户随时看到
还能调用多少次。

本模块只做「MCP 协议适配」一件事；业务逻辑在 commands.py，格式化在 formatters.py。
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from . import commands, credentials, formatters
from .quota import QuotaTracker
from .upstream.base import McpError
from .upstream.http_client import ZhihuRestClient


mcp = FastMCP("zhihu-search")

# 单例客户端；进程内只创建一次。
_client: ZhihuRestClient | None = None


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


def _ok(text: str, quota: commands.CommandResult | QuotaTracker | None = None) -> dict:
    """正常返回：业务文本 + 配额提示。"""
    body = text.rstrip()
    if body:
        body += "\n\n"
    if isinstance(quota, commands.CommandResult) and quota.quota is not None:
        body += quota.quota.to_line()
    elif isinstance(quota, QuotaTracker):
        body += quota.snapshot().to_line()
    return {"content": [{"type": "text", "text": body}], "isError": False}


def _err(message: str, quota: commands.CommandResult | None = None) -> dict:
    """错误返回：错误文本 + 配额提示（如果能拿到）。"""
    text = f"[错误] {message}"
    if quota is not None and quota.quota is not None:
        text += f"\n\n{quota.quota.to_line()}"
    return {"content": [{"type": "text", "text": text}], "isError": True}


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
    query: str,
    scope: Literal["zhihu", "web"] = "zhihu",
    count: int = 10,
    filter: str = "",
) -> dict:
    """搜索知乎内容。

    Args:
        query: 搜索关键词，2-100 字符。
        scope: 'zhihu' 站内 / 'web' 全网。
        count: 返回条数（zhihu 1-10，web 1-20，默认 10）。
        filter: 高级筛选表达式，仅 scope='web' 生效，例如
            ``host=="example.com" AND publish_time>=1778494631``。
    """
    try:
        client = _get_client()
    except credentials.CredentialsError as e:
        return _err(str(e))
    result = await commands.run_search(
        query=query, scope=scope, count=count, filter=filter,
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
    query: str,
    model: Literal["fast", "thinking", "agent"] = "fast",
) -> dict:
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
async def trending(limit: int = 30) -> dict:
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


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------


def main() -> None:
    """以 stdio 模式启动 MCP 服务器。"""
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
