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

from dataclasses import dataclass, field
from typing import Any, Optional

from . import credentials
from .quota import QuotaKind, QuotaSnapshot, QuotaTracker
from .upstream.base import McpError, RateLimited
from .upstream.http_client import ZhihuRestClient


@dataclass
class CommandResult:
    """一次命令调用的完整结果。"""

    success: bool
    data: Optional[dict] = None
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
    label = {"search": "搜索", "trending": "热榜", "ask": "直答"}.get(kind, kind)
    return f"{label}接口已被熔断，剩余冷却约 {secs} 秒，请稍后重试。"


def _kind_for_scope(scope: str) -> QuotaKind:
    """``scope`` 参数映射到配额类别。搜索和全网搜索都走 ``search`` 桶。"""
    return "search"


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
    client: ZhihuRestClient | None = None,
) -> CommandResult:
    """搜索知乎内容。

    Args:
        query: 搜索关键词。
        scope: ``zhihu``（站内）或 ``web``（全网）。
        count: 返回条数。
        filter: 高级筛选，仅 ``scope='web'`` 生效。
        client: 可复用的客户端实例（MCP 场景传入）。

    Returns:
        :class:`CommandResult`，success 为 True 时 data 含 API 响应体。
    """
    own, owns = _make_client(client)
    tracker = own.quota_tracker
    kind: QuotaKind = "search"

    # 熔断检查
    if not tracker.is_allowed(kind):
        return CommandResult(
            success=False,
            error=_breaker_open_msg(kind, tracker),
            quota=tracker.snapshot(),
        )

    try:
        if scope == "zhihu":
            result = await own.zhihu_search(query=query, count=count)
        else:
            result = await own.global_search(
                query=query, count=count, filter=filter, search_db="all"
            )
        tracker.record_success(kind)
        return CommandResult(
            success=True,
            data=result.data,
            quota=result.quota,
            headers=result.headers,
        )
    except RateLimited as e:
        tracker.record_failure(kind)
        return CommandResult(
            success=False,
            error=str(e),
            quota=tracker.snapshot(),
        )
    except McpError as e:
        return CommandResult(
            success=False,
            error=str(e),
            quota=tracker.snapshot(),
        )
    except Exception as e:
        return CommandResult(success=False, error=f"未预期错误：{e}")
    finally:
        await _try_close(own, owns)


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
    own, owns = _make_client(client)
    tracker = own.quota_tracker
    kind: QuotaKind = "ask"
    mapped = _MODEL_MAP.get(model, "zhida-fast-1p5")

    if not tracker.is_allowed(kind):
        return CommandResult(
            success=False,
            error=_breaker_open_msg(kind, tracker),
            quota=tracker.snapshot(),
        )

    try:
        result = await own.zhida(query=query, model=mapped)
        tracker.record_success(kind)
        return CommandResult(
            success=True,
            data=result.data,
            quota=result.quota,
            headers=result.headers,
        )
    except RateLimited as e:
        tracker.record_failure(kind)
        return CommandResult(
            success=False,
            error=str(e),
            quota=tracker.snapshot(),
        )
    except McpError as e:
        return CommandResult(
            success=False,
            error=str(e),
            quota=tracker.snapshot(),
        )
    except Exception as e:
        return CommandResult(success=False, error=f"未预期错误：{e}")
    finally:
        await _try_close(own, owns)


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
    own, owns = _make_client(client)
    tracker = own.quota_tracker
    kind: QuotaKind = "trending"

    if not tracker.is_allowed(kind):
        return CommandResult(
            success=False,
            error=_breaker_open_msg(kind, tracker),
            quota=tracker.snapshot(),
        )

    try:
        result = await own.hot_list(limit=limit)
        tracker.record_success(kind)
        return CommandResult(
            success=True,
            data=result.data,
            quota=result.quota,
            headers=result.headers,
        )
    except RateLimited as e:
        tracker.record_failure(kind)
        return CommandResult(
            success=False,
            error=str(e),
            quota=tracker.snapshot(),
        )
    except McpError as e:
        return CommandResult(
            success=False,
            error=str(e),
            quota=tracker.snapshot(),
        )
    except Exception as e:
        return CommandResult(success=False, error=f"未预期错误：{e}")
    finally:
        await _try_close(own, owns)
