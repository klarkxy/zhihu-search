"""知乎同步发布用的 OpenAPI 凭证。

与搜索 Access Secret（``ZHIHU_ACCESS_SECRET``）分开。发布签名使用：

- ``ZHIHU_OPENAPI_APP_KEY``：知乎个人主页 URL 中的用户名
- ``ZHIHU_OPENAPI_APP_SECRET``：发布 OpenAPI 的访问密钥

读取顺序：

1. 两个环境变量都存在且完整；
2. ``~/.config/zhihu-search/openapi-credentials.json``
   （``ZHIHU_SEARCH_HOME`` 可改根目录）；
3. 官方同步助手使用的共享文件 ``~/.zhihu/openapi-credentials.json``。

环境变量和文件都完整但不一致时拒绝猜测。检查和错误文本可以说明来源和
App Key（主页用户名），但不得包含 App Secret。保存时支持知乎授权说明原文，
其中两项都写成 ``ZHIHU_OPENAPI_APP_KEY:"…"`` 与
``ZHIHU_OPENAPI_APP_SECRET:"…"``。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from . import credentials


ENV_APP_KEY = "ZHIHU_OPENAPI_APP_KEY"
ENV_APP_SECRET = "ZHIHU_OPENAPI_APP_SECRET"
FILE_NAME = "openapi-credentials.json"

_GRANT_KEY = re.compile(r'ZHIHU_OPENAPI_APP_KEY\s*[:=]\s*"([^"\r\n]+)"')
_GRANT_SECRET = re.compile(r'ZHIHU_OPENAPI_APP_SECRET\s*[:=]\s*"([^"\r\n]+)"')
_GRANT_MARKER = re.compile(r"ZHIHU_OPENAPI_APP_(?:KEY|SECRET)")

_KEY_FIELDS = (ENV_APP_KEY, "app_key", "appKey")
_SECRET_FIELDS = (ENV_APP_SECRET, "app_secret", "appSecret")


class OpenApiCredentialsError(RuntimeError):
    """发布凭证缺失、不完整或来源冲突。"""


@dataclass(frozen=True)
class OpenApiCredentials:
    """解析后的发布凭证。``app_secret`` 不得写入日志或工具结果。"""

    app_key: str
    app_secret: str
    source: str  # "env" | "file" | "shared"


def shared_credentials_path() -> Path:
    """官方知乎 OpenAPI skill 共用的凭证文件。测试可替换此函数。"""
    return Path.home() / ".zhihu" / "openapi-credentials.json"


def credentials_path() -> Path:
    """本包保存发布凭证的位置。"""
    return credentials.credentials_dir() / FILE_NAME


def looks_like_authorization(text: str) -> bool:
    """文本里出现了授权字段名，但未必能解析出成对凭证。"""
    return bool(_GRANT_MARKER.search(text or ""))


def parse_authorization(text: str) -> tuple[str, str] | None:
    """从授权说明或 JSON 中提取成对凭证。

    只接受两项都被双引号写出的授权说明，或同时包含两项的 JSON 对象。
    解析失败时返回 ``None``，调用方不得把整段原文当成密钥保存。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("{") and raw.endswith("}"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            pair = _pair_from_mapping(payload)
            if pair is not None:
                return pair
    key_match = _GRANT_KEY.search(raw)
    secret_match = _GRANT_SECRET.search(raw)
    if key_match is None or secret_match is None:
        return None
    return _validated_pair(key_match.group(1), secret_match.group(1))


def save_authorization(text: str) -> Path:
    """解析授权说明并写入本包凭证文件。不修改 ``~/.zhihu`` 共享文件。"""
    if looks_like_authorization(text) and parse_authorization(text) is None:
        raise OpenApiCredentialsError(
            "这段文字含有知乎发布凭证标记，但没能读出成对的 "
            'ZHIHU_OPENAPI_APP_KEY:"…" 与 ZHIHU_OPENAPI_APP_SECRET:"…"。'
            "不会保存整段原文。"
        )
    pair = parse_authorization(text)
    if pair is None:
        raise OpenApiCredentialsError(
            "请粘贴完整授权说明，其中同时包含 "
            'ZHIHU_OPENAPI_APP_KEY:"…" 和 ZHIHU_OPENAPI_APP_SECRET:"…"。'
        )
    return save_pair(*pair)


def save_pair(app_key: str, app_secret: str) -> Path:
    """写入已拆开的两项凭证。"""
    pair = _validated_pair(app_key, app_secret)
    if pair is None:
        raise OpenApiCredentialsError("App Key 或 App Secret 无效。")
    path = credentials_path()
    payload = {
        ENV_APP_KEY: pair[0],
        ENV_APP_SECRET: pair[1],
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_secret_file(path, payload)
    return path


def clear() -> bool:
    """删除本包保存的发布凭证。不删除官方共享文件。"""
    path = credentials_path()
    if path.is_file():
        path.unlink()
        return True
    return False


def load() -> OpenApiCredentials:
    """按环境变量、本地文件、共享文件的顺序解析，冲突则失败。"""
    env_pair, env_partial = _env_pair()
    if env_partial:
        raise OpenApiCredentialsError(
            "ZHIHU_OPENAPI_APP_KEY 与 ZHIHU_OPENAPI_APP_SECRET 必须同时设置。"
        )
    local = _read_file(credentials_path(), "本地 OpenAPI 凭证文件")
    shared = _read_file(shared_credentials_path(), "共享 OpenAPI 凭证文件")
    if env_pair is not None:
        for label, pair in (("本地 OpenAPI 凭证文件", local), ("共享 OpenAPI 凭证文件", shared)):
            if pair is not None and pair != env_pair:
                raise OpenApiCredentialsError(_conflict_message("环境变量", env_pair, label, pair))
        return OpenApiCredentials(*env_pair, source="env")
    if local is not None and shared is not None and local != shared:
        raise OpenApiCredentialsError(
            _conflict_message("本地 OpenAPI 凭证文件", local, "共享 OpenAPI 凭证文件", shared)
        )
    if local is not None:
        return OpenApiCredentials(*local, source="file")
    if shared is not None:
        return OpenApiCredentials(*shared, source="shared")
    raise OpenApiCredentialsError(
        "未找到知乎发布 OpenAPI 凭证。它与搜索 Access Secret 不是同一项。\n"
        "  - 设置 ZHIHU_OPENAPI_APP_KEY 与 ZHIHU_OPENAPI_APP_SECRET\n"
        "  - 或执行 zhihu-search --save-openapi \"<授权说明全文>\"\n"
        "申请入口：https://www.zhihu.com/playground/zhihu-sync"
    )


def describe() -> dict[str, object]:
    """凭证状态。成功时包含来源和 App Key，永不包含 App Secret。"""
    try:
        creds = load()
    except OpenApiCredentialsError as exc:
        return {"configured": False, "source": None, "app_key": None, "detail": str(exc)}
    return {"configured": True, "source": creds.source, "app_key": creds.app_key}


def _env_pair() -> tuple[tuple[str, str] | None, bool]:
    key = os.environ.get(ENV_APP_KEY)
    secret = os.environ.get(ENV_APP_SECRET)
    key_set = bool(key and key.strip())
    secret_set = bool(secret and secret.strip())
    if key_set ^ secret_set:
        return None, True
    if not key_set:
        return None, False
    pair = _validated_pair(key or "", secret or "")
    if pair is None:
        raise OpenApiCredentialsError("环境变量中的发布凭证无效。")
    return pair, False


def _read_file(path: Path, label: str) -> tuple[str, str] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OpenApiCredentialsError(f"{label}无法读取。") from exc
    if not isinstance(payload, dict):
        raise OpenApiCredentialsError(f"{label}格式无效。")
    pair = _pair_from_mapping(payload)
    if pair is None:
        present = any(payload.get(name) for name in _KEY_FIELDS + _SECRET_FIELDS)
        if present:
            raise OpenApiCredentialsError(f"{label}不完整。")
        return None
    return pair


def _pair_from_mapping(payload: Mapping[str, object]) -> tuple[str, str] | None:
    key = _first_text(payload, _KEY_FIELDS)
    secret = _first_text(payload, _SECRET_FIELDS)
    if key is None and secret is None:
        return None
    if key is None or secret is None:
        return None
    return _validated_pair(key, secret)


def _first_text(payload: Mapping[str, object], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _validated_pair(app_key: str, app_secret: str) -> tuple[str, str] | None:
    key = app_key.strip()
    secret = app_secret.strip()
    if not key or not secret or key == secret:
        return None
    if any(ch in key or ch in secret for ch in "\r\n\x00"):
        return None
    if not 1 <= len(key) <= 128 or not 8 <= len(secret) <= 512:
        return None
    return key, secret


def _conflict_message(
    left_label: str,
    left: tuple[str, str],
    right_label: str,
    right: tuple[str, str],
) -> str:
    if left[0] != right[0]:
        identity = (
            f"{left_label}的 App Key 是 {left[0]}，"
            f"{right_label}的 App Key 是 {right[0]}。"
        )
    else:
        identity = "两处 App Key 相同，但 App Secret 不一致。"
    return (
        f"发布凭证来源冲突：{left_label}与{right_label}不一致。{identity}"
        "请只保留一个来源，或把两边改成相同的一对凭证。本次不会发送请求。"
    )


def _write_secret_file(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:  # pragma: no cover - Windows
        pass
    temporary.replace(path)
