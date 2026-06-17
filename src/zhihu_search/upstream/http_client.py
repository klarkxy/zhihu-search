"""统一 REST 客户端：包揽 4 个知乎开放平台数据接口。

接口规范（参见 https://developer.zhihu.com/docs）：

+---------------------+----------------------------------------------------------+
| 接口                | URL                                                       |
+=====================+==========================================================+
| 知乎搜索            | GET  /api/v1/content/zhihu_search?Query=&Count=          |
| 全网搜索            | GET  /api/v1/content/global_search?Query=&Count=&...     |
| 热榜                | GET  /api/v1/content/hot_list?Limit=                     |
| 直答（chat 形式）   | POST /v1/chat/completions  body={model,messages,stream}  |
+---------------------+----------------------------------------------------------+

公共 Header：
    Authorization: Bearer <access_secret>
    X-Request-Timestamp: <秒级 unix 时间戳>
    Content-Type: application/json

公共响应信封（搜索、热榜）：``{Code, Message, Data}``
直答响应：OpenAI Chat Completion 兼容格式。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal, Optional

import httpx

from .base import (
    InvalidArguments,
    McpError,
    RateLimited,
    TokenInvalid,
    UpstreamTimeout,
    UpstreamUnavailable,
    parse_retry_after,
)
from ..quota import QuotaKind, QuotaSnapshot, QuotaTracker


BASE_URL = "https://developer.zhihu.com"

# 知乎响应信封的错误码映射
_CODE_TO_ERROR: dict[int, type[McpError]] = {
    10001: InvalidArguments,    # 参数错误
    20001: TokenInvalid,        # 鉴权失败
    30001: RateLimited,         # 频率限制
    90001: UpstreamUnavailable, # 内部错误
}

# 直答模型档位（OpenAI 兼容）
ZhidaModel = Literal["zhida-fast-1p5", "zhida-thinking-1p5", "zhida-agent"]

# 各接口的参数上下界
ZHIHU_SEARCH_MAX = 10
GLOBAL_SEARCH_MAX = 20
HOT_LIST_MAX = 30
QUERY_MIN = 2
QUERY_MAX = 100

DEFAULT_TIMEOUT = 30.0
ZHIDA_TIMEOUT = 120.0  # agent 模型可能慢


@dataclass
class ApiResult:
    """一次调用后的完整结果：业务数据 + 配额快照。

    ``headers`` 里如果知乎返回了限流相关头（X-RateLimit-* 等），
    会原样带上，方便上层透传给用户。
    """

    data: Any
    quota: QuotaSnapshot
    headers: dict[str, str]


class ZhihuRestClient:
    """一个实例覆盖 4 个接口，共享连接池与配额计数。"""

    def __init__(
        self,
        access_secret: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        client: Optional[httpx.AsyncClient] = None,
        quota_tracker: Optional[QuotaTracker] = None,
    ) -> None:
        self._access_secret = access_secret
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(
            timeout=timeout, base_url=BASE_URL
        )
        self._owns_client = client is None
        self._quota = quota_tracker or QuotaTracker()

    # ------------------------------------------------------------------
    # 公共：构造请求 / 解析响应
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_secret}",
            "X-Request-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _envelope_get(
        self,
        path: str,
        params: dict[str, Any],
        *,
        kind: QuotaKind = "search",
        timeout: float | None = None,
    ) -> ApiResult:
        try:
            resp = await self._client.get(
                path, params=params, headers=self._headers(),
                timeout=timeout or self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout(f"{path} 请求超时") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"{path} 网络错误：{exc}") from exc
        return self._parse_envelope(resp, path, kind=kind)

    async def _envelope_post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        kind: QuotaKind = "search",
        timeout: float | None = None,
    ) -> ApiResult:
        try:
            resp = await self._client.post(
                path, json=body, headers=self._headers(),
                timeout=timeout or self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout(f"{path} 请求超时") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"{path} 网络错误：{exc}") from exc
        return self._parse_envelope(resp, path, kind=kind)

    def _parse_envelope(
        self,
        resp: httpx.Response,
        path: str,
        *,
        kind: QuotaKind = "search",
    ) -> ApiResult:
        """解析 ``{Code, Message, Data}`` 信封。直答走 OpenAI 格式，单独处理。"""
        # HTTP 层错误
        if resp.status_code in (401, 403):
            raise TokenInvalid()
        if resp.status_code == 429:
            retry = parse_retry_after(resp.headers.get("Retry-After"))
            raise RateLimited(
                f"{path} 被限流（HTTP 429），retry-after={retry}s",
                retry_after=retry,
            )
        if resp.status_code >= 500:
            raise UpstreamUnavailable(f"{path} 服务端错误 HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise UpstreamUnavailable(
                f"{path} HTTP {resp.status_code}：{resp.text[:200]}"
            )

        try:
            body = resp.json()
        except Exception as exc:
            raise UpstreamUnavailable(
                f"{path} 响应非 JSON：{resp.text[:200]}"
            ) from exc

        code = body.get("Code")
        if code is None:
            # 不是信封格式（说明是直答，走 OpenAI chat 流程）
            raise InvalidArguments(
                f"{path} 响应缺少 Code 字段，可能不是信封接口"
            )
        if code != 0:
            err_cls = _CODE_TO_ERROR.get(int(code), UpstreamUnavailable)
            msg = body.get("Message") or "未知错误"
            if err_cls is RateLimited:
                raise RateLimited(f"{path} 限流：{msg}")
            if err_cls is TokenInvalid:
                raise TokenInvalid()
            if err_cls is InvalidArguments:
                raise InvalidArguments(f"{path} 参数错误：{msg}")
            raise UpstreamUnavailable(f"{path} 返回错误 {code}：{msg}")

        quota = self._quota.increment(kind)
        return ApiResult(
            data=body.get("Data", {}),
            quota=quota,
            headers={k: v for k, v in resp.headers.items()},
        )

    # ------------------------------------------------------------------
    # 4 个业务接口
    # ------------------------------------------------------------------

    async def zhihu_search(
        self, query: str, count: int = 10
    ) -> ApiResult:
        """知乎站内搜索。count 自动截断到 1-10。"""
        self._validate_query(query)
        count = max(1, min(ZHIHU_SEARCH_MAX, count))
        return await self._envelope_get(
            "/api/v1/content/zhihu_search",
            {"Query": query, "Count": count},
            kind="search",
        )

    async def global_search(
        self,
        query: str,
        count: int = 10,
        filter: str = "",
        search_db: Literal["all", "realtime", "static"] = "all",
    ) -> ApiResult:
        """全网搜索。count 自动截断到 1-20。filter 为空时不传。"""
        self._validate_query(query)
        count = max(1, min(GLOBAL_SEARCH_MAX, count))
        params: dict[str, Any] = {"Query": query, "Count": count, "SearchDB": search_db}
        if filter:
            params["Filter"] = filter
        return await self._envelope_get(
            "/api/v1/content/global_search", params, kind="search"
        )

    async def hot_list(self, limit: int = 30) -> ApiResult:
        """知乎热榜。limit 自动截断到 1-30。"""
        limit = max(1, min(HOT_LIST_MAX, limit))
        return await self._envelope_get(
            "/api/v1/content/hot_list", {"Limit": limit}, kind="trending"
        )

    async def zhida(
        self,
        query: str,
        model: ZhidaModel = "zhida-fast-1p5",
        stream: bool = False,
    ) -> ApiResult:
        """知乎直答。OpenAI 兼容 chat completions 接口。

        返回结构会被规整成统一信封：
            data = {
                "id": "...",
                "model": "...",
                "content": "<最终回答>",
                "reasoning_content": "<思考过程，可能为空>",
                "finish_reason": "stop",
            }
        """
        if not query.strip():
            raise InvalidArguments("直答的 query 不能为空")

        body = {
            "model": model,
            "messages": [{"role": "user", "content": query}],
            "stream": stream,
        }
        # 直答不返回信封，走 OpenAI chat 格式，单独解析
        try:
            resp = await self._client.post(
                "/v1/chat/completions",
                json=body,
                headers=self._headers(),
                timeout=ZHIDA_TIMEOUT,
            )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout(
                f"直答请求超时（>{ZHIDA_TIMEOUT}s）；如使用 agent 模型请改 fast"
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"直答网络错误：{exc}") from exc

        if resp.status_code in (401, 403):
            raise TokenInvalid()
        if resp.status_code == 429:
            retry = parse_retry_after(resp.headers.get("Retry-After"))
            raise RateLimited(
                f"直答限流，retry-after={retry}s",
                retry_after=retry,
            )
        if resp.status_code >= 400:
            raise UpstreamUnavailable(
                f"直答 HTTP {resp.status_code}：{resp.text[:200]}"
            )

        try:
            payload = resp.json()
        except Exception as exc:
            raise UpstreamUnavailable(
                f"直答响应非 JSON：{resp.text[:200]}"
            ) from exc

        if "error" in payload:
            err = payload["error"]
            raise UpstreamUnavailable(f"直答错误：{err.get('message', err)}")

        choices = payload.get("choices") or []
        if not choices:
            raise UpstreamUnavailable("直答返回为空 choices")
        msg = choices[0].get("message") or {}
        normalized = {
            "id": payload.get("id"),
            "model": payload.get("model"),
            "content": msg.get("content", ""),
            "reasoning_content": msg.get("reasoning_content", ""),
            "finish_reason": choices[0].get("finish_reason"),
        }

        quota = self._quota.increment("ask")
        return ApiResult(
            data=normalized,
            quota=quota,
            headers={k: v for k, v in resp.headers.items()},
        )

    # ------------------------------------------------------------------
    # 资源管理
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "ZhihuRestClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    @property
    def quota_tracker(self) -> QuotaTracker:
        return self._quota

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_query(query: str) -> None:
        if not (QUERY_MIN <= len(query) <= QUERY_MAX):
            raise InvalidArguments(
                f"query 长度需在 {QUERY_MIN}-{QUERY_MAX} 字符之间（当前 {len(query)}）"
            )


__all__ = [
    "ZhihuRestClient",
    "ApiResult",
    "ZHIHU_SEARCH_MAX",
    "GLOBAL_SEARCH_MAX",
    "HOT_LIST_MAX",
    "QUERY_MIN",
    "QUERY_MAX",
]