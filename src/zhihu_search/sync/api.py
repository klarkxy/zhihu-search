"""知乎发布 OpenAPI 的 HMAC 签名请求。

签名字符串与知乎同步助手 publish-openapi 说明一致::

    app_key:{key}|ts:{timestamp}|logid:{log_id}|extra_info:{extra}
    X-Sign = Base64(HMAC-SHA256(sign_string, app_secret))

请求只发往 ``https://openapi.zhihu.com``。App Secret、签名值和上游消息里的
密钥不会进入异常文本。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time
import uuid
from typing import Mapping
from urllib.parse import urlsplit

import httpx

from ..openapi_credentials import OpenApiCredentials, OpenApiCredentialsError, load

ALLOWED_ORIGIN = "https://openapi.zhihu.com"
PUBLISH_PATH = "/openapi/publish"
_SIGNED_HEADERS = frozenset(
    {"content-type", "x-app-key", "x-timestamp", "x-log-id", "x-extra-info", "x-sign"}
)
_ZHIHU_HOST = re.compile(
    r"^(?:[a-z0-9-]+\.)*(?:zhimg\.com|zhihu\.com)$",
    re.IGNORECASE,
)


class SyncApiError(RuntimeError):
    """发布或媒体接口错误。``definite`` 为假时结果不确定，不能盲目重试。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        definite: bool,
        http_status: int | None = None,
        upstream_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.definite = definite
        self.http_status = http_status
        self.upstream_status = upstream_status


def sign_request(app_key: str, timestamp: str, log_id: str, extra_info: str, app_secret: str) -> str:
    payload = f"app_key:{app_key}|ts:{timestamp}|logid:{log_id}|extra_info:{extra_info}"
    digest = hmac.new(app_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


async def publish_prepared(
    prepared: Mapping[str, object],
    *,
    client: httpx.AsyncClient | None = None,
    credentials: OpenApiCredentials | None = None,
) -> dict[str, object]:
    """发送已确认的发布请求。调用方必须先完成预览确认。"""
    from .content import build_publish_request

    request = build_publish_request(prepared)
    data, http_status = await sync_request(
        "POST",
        PUBLISH_PATH,
        body=request,
        client=client,
        credentials=credentials,
        envelope=True,
    )
    if not isinstance(data, Mapping):
        raise SyncApiError("BAD_RESPONSE", "发布成功响应缺少 data。", definite=False, http_status=http_status)
    content_token = data.get("content_token")
    url = data.get("url")
    content_type = data.get("type")
    token = str(content_token) if isinstance(content_token, (str, int)) and str(content_token) else ""
    link = url if isinstance(url, str) else ""
    if not token or not link:
        raise SyncApiError("BAD_RESPONSE", "发布成功响应缺少 content_token 或 url。", definite=False, http_status=http_status)
    if not _safe_zhihu_url(link):
        raise SyncApiError("BAD_RESPONSE", "发布成功响应里的 url 不是知乎 HTTPS 地址。", definite=False, http_status=http_status)
    if content_type != request["type"]:
        raise SyncApiError("BAD_RESPONSE", "发布成功响应的 type 与请求不一致。", definite=False, http_status=http_status)
    return {"type": str(content_type), "url": link, "content_token": token, "http_status": http_status}


async def sync_request(
    method: str,
    path_or_url: str,
    *,
    body: object | None = None,
    headers: Mapping[str, str] | None = None,
    extra_info: str | None = None,
    client: httpx.AsyncClient | None = None,
    credentials: OpenApiCredentials | None = None,
    envelope: bool = False,
) -> tuple[object, int]:
    """签名并发送一次 OpenAPI 请求。带 ``status`` 的响应按发布信封解包。"""
    url = _allowed_url(path_or_url)
    try:
        creds = credentials or load()
    except OpenApiCredentialsError as exc:
        raise SyncApiError("TOKEN_MISSING", str(exc), definite=True) from exc
    timestamp = str(int(time.time()))
    log_id = uuid.uuid4().hex
    extra = os.environ.get("ZHIHU_PUBLISH_EXTRA_INFO", "") if extra_info is None else extra_info
    signature = sign_request(creds.app_key, timestamp, log_id, extra, creds.app_secret)
    signed = {
        "Content-Type": "application/json",
        "X-App-Key": creds.app_key,
        "X-Timestamp": timestamp,
        "X-Log-Id": log_id,
        "X-Extra-Info": extra,
        "X-Sign": signature,
    }
    for name, value in (headers or {}).items():
        if name.lower() in _SIGNED_HEADERS:
            raise SyncApiError("INVALID_URL", f"不能覆盖签名头 {name}。", definite=True)
        signed[name] = value
    secrets = [creds.app_key, creds.app_secret, signature]
    owns = client is None
    http = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)
    try:
        response = await http.request(method, url, headers=signed, json=body)
        text = response.text
    except httpx.TimeoutException as exc:
        raise SyncApiError("TIMEOUT", "发布请求超时，结果不确定。请先到知乎核对，不要立刻重发。", definite=False) from exc
    except httpx.HTTPError as exc:
        raise SyncApiError("NETWORK_ERROR", "发布请求失败，结果不确定。请先到知乎核对，不要立刻重发。", definite=False) from exc
    finally:
        if owns:
            await http.aclose()
    payload: object | None
    try:
        payload = response.json() if text else None
    except ValueError as exc:
        raise SyncApiError(
            "BAD_RESPONSE",
            f"响应不是合法 JSON（HTTP {response.status_code}）。",
            definite=False,
            http_status=response.status_code,
        ) from exc
    record = payload if isinstance(payload, dict) else None
    has_status = record is not None and "status" in record
    if has_status and isinstance(record.get("status"), int) and record["status"] != 0:
        message = _redact(record.get("msg"), secrets)
        raise SyncApiError(
            "UPSTREAM_REJECTED",
            f"发布被拒绝（status={record['status']}）：{message}",
            definite=True,
            http_status=response.status_code,
            upstream_status=record["status"],
        )
    if has_status and not isinstance(record.get("status"), int):
        raise SyncApiError(
            "BAD_RESPONSE",
            "发布响应的 status 不是数字。",
            definite=False,
            http_status=response.status_code,
        )
    if response.status_code in {301, 302, 303, 307, 308}:
        raise SyncApiError("HTTP_ERROR", "拒绝跟随发布接口重定向。", definite=True, http_status=response.status_code)
    if response.status_code < 200 or response.status_code >= 300:
        if response.status_code == 401:
            raise SyncApiError("AUTH_REJECTED", "鉴权失败（HTTP 401）。请检查发布凭证。", definite=True, http_status=401)
        if response.status_code == 429:
            raise SyncApiError("RATE_LIMITED", "发布频率超限（每人每天最多 50 次）。", definite=True, http_status=429)
        message = _redact(record.get("msg") if record else "", secrets) or "请求失败"
        raise SyncApiError(
            "HTTP_ERROR",
            f"HTTP {response.status_code}：{message}",
            definite=400 <= response.status_code < 500,
            http_status=response.status_code,
        )
    if has_status and record is not None and record.get("status") == 0:
        return record.get("data"), response.status_code
    if envelope:
        raise SyncApiError("BAD_RESPONSE", "发布响应缺少 status=0 信封。", definite=False, http_status=response.status_code)
    return payload, response.status_code


def _allowed_url(path_or_url: str) -> str:
    base = os.environ.get("ZHIHU_PUBLISH_BASE_URL", ALLOWED_ORIGIN).rstrip("/")
    if base != ALLOWED_ORIGIN:
        raise SyncApiError("INVALID_URL", "发布接口只允许 https://openapi.zhihu.com。", definite=True)
    if path_or_url.startswith("https://") or path_or_url.startswith("http://"):
        parts = urlsplit(path_or_url)
        url = path_or_url
    else:
        path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
        parts = urlsplit(ALLOWED_ORIGIN + path)
        url = ALLOWED_ORIGIN + path
    if parts.scheme != "https" or parts.username or parts.password or parts.hostname != "openapi.zhihu.com":
        raise SyncApiError("INVALID_URL", "拒绝向非知乎 OpenAPI 主机发送发布请求。", definite=True)
    return url


def _safe_zhihu_url(value: str) -> bool:
    parts = urlsplit(value)
    return (
        parts.scheme == "https"
        and not parts.username
        and bool(parts.hostname)
        and bool(_ZHIHU_HOST.match(parts.hostname))
    )


def _redact(value: object, secrets: list[str]) -> str:
    text = value if isinstance(value, str) else ""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text[:400]
