"""知乎开放平台 Access Secret 凭证管理。

解析优先级：
    1. ``ZHIHU_ACCESS_SECRET`` 环境变量（最高）
    2. ``~/.config/zhihu-search/credentials.json``（默认文件）

Windows 下 ``Path.home()`` 解析为 ``C:\\Users\\<user>``，所以这条
相对路径无需 ``%APPDATA%`` 分支就能跨平台工作。

凭证文件是明文 JSON。Bearer secret 本身已经是低权限（只对知乎开放平台
生效），在本进程读写同一个文件里加密属于演戏；Windows 下靠用户目录
隔离即可。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


ENV_VAR = "ZHIHU_ACCESS_SECRET"
DEFAULT_DIR = Path.home() / ".config" / "zhihu-search"
DEFAULT_FILE = DEFAULT_DIR / "credentials.json"

# 知乎的 Access Secret 以前缀 zh 开头（宽松校验，不强制）
_TOKEN_HINT = re.compile(r"^zh[a-z0-9_-]{8,}$")


@dataclass(frozen=True)
class Credentials:
    """解析后的凭证 + 来源标记。"""

    access_secret: str
    source: str  # "env" | "file" | "memory"
    path: Optional[Path] = None


class CredentialsError(RuntimeError):
    """凭证无法加载时抛出。"""


def _looks_like_token(value: str) -> bool:
    """宽松校验：非空且长度合理。"""
    if not value:
        return False
    v = value.strip()
    return 8 <= len(v) <= 256


def credentials_dir() -> Path:
    """凭证目录（环境变量 ``ZHIHU_SEARCH_HOME`` 可覆盖），不存在则创建。"""
    override = os.environ.get("ZHIHU_SEARCH_HOME")
    base = Path(override) if override else DEFAULT_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base


def credentials_file() -> Path:
    """凭证文件路径（不一定存在）。"""
    return credentials_dir() / "credentials.json"


def load(secret: Optional[str] = None) -> Credentials:
    """解析凭证。

    Args:
        secret: 直接传入的 secret（用于测试和 agent onboarding 流程）。

    Returns:
        :class:`Credentials`，``source`` 指明来源。

    Raises:
        CredentialsError: 找不到可用凭证时。
    """
    if secret is not None:
        if not _looks_like_token(secret):
            raise CredentialsError(
                "传入的 secret 不像合法的知乎 Access Token（长度需 8-256）。"
            )
        return Credentials(access_secret=secret.strip(), source="memory")

    env = os.environ.get(ENV_VAR)
    if env and _looks_like_token(env):
        return Credentials(access_secret=env.strip(), source="env")

    path = credentials_file()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialsError(f"读取凭证文件 {path} 失败：{exc}") from exc

        secret_value = data.get("access_secret") if isinstance(data, dict) else None
        if isinstance(secret_value, str) and _looks_like_token(secret_value):
            return Credentials(
                access_secret=secret_value.strip(),
                source="file",
                path=path,
            )

        raise CredentialsError(
            f"凭证文件 {path} 缺少有效的 'access_secret' 字段。"
        )

    raise CredentialsError(
        "未找到知乎 Access Secret。可通过以下任一方式提供：\n"
        "  - 设置环境变量 ZHIHU_ACCESS_SECRET\n"
        "  - 执行 `zhihu-search --save-token <你的 secret>`\n"
        "  - 让 agent 按 AGENT_SETUP.md 引导你获取"
    )


def save(secret: str) -> Path:
    """把 secret 持久化到默认凭证文件。"""
    if not _looks_like_token(secret):
        raise CredentialsError("传入的 secret 不像合法的知乎 Access Token。")
    path = credentials_file()
    payload = {
        "access_secret": secret.strip(),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - Windows
        pass
    return path


def clear() -> bool:
    """删除凭证文件。返回是否真的删除过。"""
    path = credentials_file()
    if path.is_file():
        path.unlink()
        return True
    return False


def hint_ok(value: str) -> bool:
    """宽松格式自检：是否匹配知乎 ``zh...`` 前缀。"""
    return bool(_TOKEN_HINT.match(value))