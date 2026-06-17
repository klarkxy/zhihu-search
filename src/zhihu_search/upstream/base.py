"""上游客户端的抽象基类 + 错误分类。

所有上游实现都遵循 :class:`UpstreamClient` 协议。服务器把
:class:`McpError` 子类翻译成 MCP ``isError: true`` 文本，让 LLM
和阅读 AGENT_SETUP.md 的 agent 都能采取行动。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class McpError(Exception):
    """所有向上抛出的上游错误基类。

    子类对应具体的可执行修复方案（见 ``AGENT_SETUP.md`` 错误目录）。
    """

    code: int = -32000  # JSON-RPC 服务端错误区间

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TokenInvalid(McpError):
    """401：token 过期或错误。

    服务器返回一段明确指引，让 agent 按 AGENT_SETUP.md 第 3 步重新引导。
    """

    code = -32001

    def __init__(self) -> None:
        super().__init__(
            "Token 已过期或无效。请到 https://developer.zhihu.com/personal "
            "重新创建并保存新的 Access Secret。"
        )


class RateLimited(McpError):
    """30001 / HTTP 429：触发限流。"""

    code = -32002


class UpstreamUnavailable(McpError):
    """网络错误、5xx、SSE 断流（保留）。"""

    code = -32003

    def __init__(self, message: str = "知乎上游暂不可达。") -> None:
        super().__init__(message)


class UpstreamTimeout(McpError):
    """请求超过限定时间。"""

    code = -32004


class UnknownTool(McpError):
    """上游没暴露请求的工具。"""

    code = -32005


class InvalidArguments(McpError):
    """本地校验失败，不会发到上游。"""

    code = -32006


@runtime_checkable
class UpstreamClient(Protocol):
    """所有上游实现的统一接口。"""

    name: str

    async def initialize(self) -> None: ...
    async def list_tools(self) -> list[dict[str, Any]]: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
    async def aclose(self) -> None: ...


def parse_retry_after(value: str | None) -> float | None:
    """解析 ``Retry-After`` 头为秒数（float），失败返回 None。"""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def is_auth_error(status: int) -> bool:
    return status in (401, 403)


def is_rate_limit(status: int) -> bool:
    return status == 429