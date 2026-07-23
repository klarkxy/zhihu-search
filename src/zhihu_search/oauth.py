"""知乎 OAuth 2.0 Authorization Code Flow helpers.

官方当前只公开了授权 URL 与 authorization code 换 token 两步。这里不
擅自添加 scope、state、PKCE、refresh token 或用户信息接口。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from .upstream.base import (
    InvalidArguments,
    RateLimited,
    UpstreamTimeout,
    UpstreamUnavailable,
    parse_retry_after,
)


OAUTH_AUTHORIZE_URL = "https://openapi.zhihu.com/authorize"
OAUTH_ACCESS_TOKEN_URL = "https://openapi.zhihu.com/access_token"
OAUTH_TIMEOUT = 30.0


def build_authorize_url(app_id: str, redirect_uri: str) -> str:
    """Build the documented Zhihu OAuth authorization URL."""
    _require_nonempty(app_id, "app_id")
    _require_nonempty(redirect_uri, "redirect_uri")
    query = urlencode(
        [
            ("redirect_uri", redirect_uri),
            ("app_id", app_id),
            ("response_type", "code"),
        ]
    )
    return f"{OAUTH_AUTHORIZE_URL}?{query}"


async def exchange_access_token(
    app_id: str,
    app_key: str,
    redirect_uri: str,
    code: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code for a validated OAuth token payload.

    The request uses ``application/x-www-form-urlencoded`` exactly as documented.
    An injected client remains owned by the caller.
    """
    _require_nonempty(app_id, "app_id")
    _require_nonempty(app_key, "app_key")
    _require_nonempty(redirect_uri, "redirect_uri")
    _require_nonempty(code, "code")

    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=OAUTH_TIMEOUT)
    try:
        try:
            response = await active_client.post(
                OAUTH_ACCESS_TOKEN_URL,
                data={
                    "app_id": app_id,
                    "app_key": app_key,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
                headers={"Accept": "application/json"},
                timeout=OAUTH_TIMEOUT,
            )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout("OAuth access_token 请求超时") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                f"OAuth access_token 网络错误：{exc}"
            ) from exc

        if response.status_code == 429:
            retry = parse_retry_after(response.headers.get("Retry-After"))
            raise RateLimited(
                f"OAuth access_token 被限流，retry-after={retry}s",
                retry_after=retry,
            )
        if response.status_code >= 500:
            raise UpstreamUnavailable(
                f"OAuth access_token 服务端错误 HTTP {response.status_code}"
            )
        if response.status_code >= 400:
            raise InvalidArguments(
                "OAuth access_token 请求失败"
                f"（HTTP {response.status_code}）：{_error_text(response)}"
            )

        try:
            payload = response.json()
        except Exception as exc:
            raise UpstreamUnavailable(
                f"OAuth access_token 响应非 JSON：{response.text[:200]}"
            ) from exc
        if not isinstance(payload, dict):
            raise UpstreamUnavailable("OAuth access_token 响应必须是 JSON 对象")

        _validate_token_payload(payload)
        return dict(payload)
    finally:
        if owns_client:
            await active_client.aclose()


def _require_nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidArguments(f"{name} 不能为空")


def _validate_token_payload(payload: dict[str, Any]) -> None:
    for field in ("access_token", "token_type"):
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            raise UpstreamUnavailable(
                f"OAuth access_token 响应缺少有效的 {field}"
            )
    expires_in = payload.get("expires_in")
    if (
        isinstance(expires_in, bool)
        or not isinstance(expires_in, int)
        or expires_in < 0
    ):
        raise UpstreamUnavailable(
            "OAuth access_token 响应缺少有效的 expires_in"
        )


def _error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return response.text[:200] or "未知错误"
    if not isinstance(payload, dict):
        return str(payload)[:200]
    for key in ("error_description", "error", "message", "msg", "Message"):
        value = payload.get(key)
        if value:
            return str(value)[:200]
    return str(payload)[:200]


__all__ = [
    "OAUTH_AUTHORIZE_URL",
    "OAUTH_ACCESS_TOKEN_URL",
    "build_authorize_url",
    "exchange_access_token",
]
