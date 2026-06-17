"""FastMCP 服务器：暴露 3 个工具，背后转发到 4 个知乎开放平台 REST 接口。

工具映射：
    search   → 知乎搜索 (scope=zhihu) 或 全网搜索 (scope=web)
    ask      → 直答（OpenAI 兼容 chat completions）
    trending → 热榜

每次返回的内容末尾会附加一行当日配额进度，让 agent / 用户随时看到
还能调用多少次。
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastmcp import FastMCP

from . import credentials
from .quota import QuotaSnapshot, QuotaTracker
from .upstream.base import (
    McpError,
    RateLimited,
    TokenInvalid,
    UpstreamTimeout,
    UpstreamUnavailable,
)
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


def _ok(text: str, quota: QuotaSnapshot) -> dict:
    """正常返回：业务文本 + 配额提示。"""
    body = text.rstrip()
    if body:
        body += "\n\n"
    body += quota.to_line()
    return {"content": [{"type": "text", "text": body}], "isError": False}


def _err(message: str, quota: QuotaSnapshot | None = None) -> dict:
    """错误返回：错误文本 + 配额提示（如果能拿到）。"""
    text = f"[错误] {message}"
    if quota is not None:
        text += f"\n\n{quota.to_line()}"
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _translate(e: Exception, tracker: QuotaTracker | None = None) -> dict:
    quota = tracker.snapshot() if tracker is not None else None
    if isinstance(e, McpError):
        return _err(str(e), quota)
    return _err(f"未预期错误：{e}", quota)


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
    client = _get_client()
    tracker = client.quota_tracker

    if scope == "zhihu":
        try:
            result = await client.zhihu_search(query=query, count=count)
        except McpError as e:
            return _translate(e, tracker)
        except Exception as e:
            return _translate(e, tracker)
        return _ok(_format_search_items(result.data, scope="zhihu"), result.quota)

    # scope == "web"
    try:
        result = await client.global_search(
            query=query, count=count, filter=filter, search_db="all"
        )
    except McpError as e:
        return _translate(e, tracker)
    except Exception as e:
        return _translate(e, tracker)
    return _ok(_format_search_items(result.data, scope="web"), result.quota)


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
    client = _get_client()
    tracker = client.quota_tracker

    model_map = {
        "fast": "zhida-fast-1p5",
        "thinking": "zhida-thinking-1p5",
        "agent": "zhida-agent",
    }
    try:
        result = await client.zhida(query=query, model=model_map[model])
    except McpError as e:
        return _translate(e, tracker)
    except Exception as e:
        return _translate(e, tracker)

    parts = []
    if result.data.get("reasoning_content"):
        parts.append(f"【思考过程】\n{result.data['reasoning_content']}")
    parts.append(result.data.get("content") or "")
    return _ok("\n\n".join(parts).strip(), result.quota)


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
    client = _get_client()
    tracker = client.quota_tracker

    try:
        result = await client.hot_list(limit=limit)
    except McpError as e:
        return _translate(e, tracker)
    except Exception as e:
        return _translate(e, tracker)
    return _ok(_format_hot_items(result.data), result.quota)


# ----------------------------------------------------------------------
# 格式化
# ----------------------------------------------------------------------


def _format_search_items(data: dict, scope: str) -> str:
    """把搜索结果格式化成易读的 Markdown 文本。"""
    items = data.get("Items") or []
    if not items:
        empty_reason = data.get("EmptyReason") or "无结果"
        return f"未找到匹配内容（{empty_reason}）。"

    lines: list[str] = []
    for idx, item in enumerate(items, 1):
        title = item.get("Title") or "(无标题)"
        ctype = item.get("ContentType") or "内容"
        url = item.get("Url") or ""
        summary = (item.get("ContentText") or "").strip()
        votes = item.get("VoteUpCount", 0)
        comments = item.get("CommentCount", 0)
        author = item.get("AuthorName") or "匿名"
        auth_level = item.get("AuthorityLevel") or "?"
        edit_time = item.get("EditTime")
        edit_time_str = (
            _format_timestamp(edit_time) if isinstance(edit_time, int) else ""
        )

        lines.append(f"### {idx}. {title}")
        lines.append(f"- 类型：{ctype}　|　作者：{author}　|　权威：{auth_level}")
        lines.append(f"- 链接：{url}")
        if edit_time_str:
            lines.append(f"- 时间：{edit_time_str}")
        lines.append(f"- 数据：赞同 {votes}　|　评论 {comments}")
        if summary:
            lines.append("")
            lines.append(_truncate(summary, 400))
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_hot_items(data: dict) -> str:
    """热榜格式化。"""
    items = data.get("Items") or []
    if not items:
        return "热榜为空。"
    lines: list[str] = ["## 知乎热榜\n"]
    for rank, item in enumerate(items, 1):
        title = item.get("Title") or "(无标题)"
        url = item.get("Url") or ""
        thumb = item.get("ThumbnailUrl") or ""
        summary = item.get("Summary") or ""
        lines.append(f"**{rank}. {title}**")
        if url:
            lines.append(url)
        if thumb:
            lines.append(f"封面：{thumb}")
        if summary:
            lines.append(_truncate(summary, 200))
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_timestamp(ts: int) -> str:
    """秒级时间戳 → 'YYYY-MM-DD HH:MM'。"""
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    except (OverflowError, OSError, ValueError):
        return str(ts)


def _truncate(text: str, limit: int) -> str:
    text = text.strip().replace("\r\n", "\n")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


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