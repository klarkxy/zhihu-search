"""每日调用配额追踪。

知乎开放平台官方文档没明确返回 ``X-RateLimit-*`` 响应头，所以我们
本地维护一份「今日调用次数」统计，附在每次返回给 agent 的内容里。
这样 agent 能在接近上限时主动收敛行为。

配额按「接口类别」分开计数（与知乎开发者后台的展示口径一致）：

- ``search`` ：知乎搜索 + 全网搜索
- ``trending``：热榜
- ``ask``    ：直答（含 fast / thinking / agent 三个模型）

存储位置：``~/.config/zhihu-search/quota.json``
覆盖位置：通过 ``ZHIHU_SEARCH_HOME`` 环境变量。
默认上限：通过 ``ZHIHU_DAILY_LIMIT`` 环境变量（统一 1000，向后兼容）；
推荐改用 ``ZHIHU_DAILY_LIMIT_SEARCH`` / ``..._TRENDING`` / ``..._ASK``
分别覆盖。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Literal, Optional


QuotaKind = Literal["search", "trending", "ask"]

#: 各接口的真实默认上限（与知乎开发者后台的展示口径一致）。
DEFAULT_LIMITS: dict[QuotaKind, int] = {
    "search": 5000,
    "trending": 100,
    "ask": 100,
}

#: 向后兼容的「统一上限」常量（旧测试 / 旧环境变量）。
DEFAULT_DAILY_LIMIT = 1000
QUOTA_FILE = "quota.json"


def _today() -> str:
    return date.today().isoformat()


def _next_reset_iso() -> str:
    from datetime import timedelta

    tomorrow = date.today() + timedelta(days=1)
    return f"{tomorrow.isoformat()}T00:00:00"


_KIND_LABELS: dict[str, str] = {
    "search": "搜索",
    "trending": "热榜",
    "ask": "直答",
}


@dataclass
class QuotaSnapshot:
    """某次调用后的配额快照，跟随响应一起返回。

    ``by_kind`` 把每个接口的「已用 / 上限」分列出来；``total`` 给出
    全局（不区分接口）的视角，用于向前兼容 / 历史展示。
    """

    by_kind: dict[str, dict[str, int]] = field(default_factory=dict)
    reset_at: str = ""

    @property
    def used(self) -> int:
        return sum(item["used"] for item in self.by_kind.values())

    @property
    def limit(self) -> int:
        return sum(item["limit"] for item in self.by_kind.values())

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def to_line(self) -> str:
        """一行可读的进度文本，附加在工具返回文本末尾。

        多个接口类别用「·」连接；余量为 0 的类别后跟耗尽提示。
        """
        parts: list[str] = []
        for kind, info in self.by_kind.items():
            label = _KIND_LABELS.get(kind, kind)
            piece = f"{label} {info['used']}/{info['limit']}"
            if info["remaining"] == 0:
                piece += "（已耗尽）"
            parts.append(piece)
        summary = " · ".join(parts) if parts else "（无记录）"
        return f"配额：{summary}（{self.reset_at} 刷新）"

    def to_block(self) -> str:
        """多行版，CLI ``--quota`` 调试用。"""
        lines: list[str] = []
        for kind, info in self.by_kind.items():
            label = _KIND_LABELS.get(kind, kind)
            lines.append(
                f"  {label}：{info['used']}/{info['limit']}（剩 {info['remaining']}）"
            )
        return "\n".join(lines) if lines else "（无记录）"


class QuotaTracker:
    """进程内 + 文件双层计数的配额追踪器。

    - 进程内：``asyncio`` 任务安全（我们用 threading.Lock 简化；
      单次写读窗口内并发一致即可）
    - 文件：每次 ``increment`` 后立即落盘，重启进程后计数延续
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        daily_limit: Optional[int] = None,
        # 新接口：按类别覆盖上限
        limits: Optional[dict[QuotaKind, int]] = None,
    ) -> None:
        self._dir = base_dir or self._default_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / QUOTA_FILE
        self._limits = self._resolve_limits(daily_limit, limits)
        self._lock = Lock()
        self._state = self._load()

    # ------------------------------------------------------------------
    # 配置 / 持久化
    # ------------------------------------------------------------------

    @staticmethod
    def _default_dir() -> Path:
        override = os.environ.get("ZHIHU_SEARCH_HOME")
        return Path(override) if override else Path.home() / ".config" / "zhihu-search"

    @classmethod
    def _resolve_limits(
        cls,
        daily_limit: Optional[int],
        explicit: Optional[dict[QuotaKind, int]],
    ) -> dict[QuotaKind, int]:
        """合并优先级：显式 limits 参数 > 环境变量 > 默认值。"""
        merged: dict[QuotaKind, int] = dict(DEFAULT_LIMITS)

        # 1. 旧环境变量（向后兼容）
        env_all = os.environ.get("ZHIHU_DAILY_LIMIT")
        if env_all and env_all.isdigit():
            for k in merged:
                merged[k] = int(env_all)

        # 2. 新环境变量（分接口）
        env_map = {
            "search": os.environ.get("ZHIHU_DAILY_LIMIT_SEARCH"),
            "trending": os.environ.get("ZHIHU_DAILY_LIMIT_TRENDING"),
            "ask": os.environ.get("ZHIHU_DAILY_LIMIT_ASK"),
        }
        for k, v in env_map.items():
            if v and v.isdigit():
                merged[k] = int(v)

        # 3. 旧参数 daily_limit（向后兼容）
        if daily_limit is not None:
            for k in merged:
                merged[k] = daily_limit

        # 4. 显式 limits（最高）
        if explicit:
            merged.update(explicit)

        return merged

    def _load(self) -> dict:
        if not self._file.is_file():
            return {"date": _today(), "counts": {k: 0 for k in self._limits}}
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            if data.get("date") != _today():
                return {
                    "date": _today(),
                    "counts": {k: 0 for k in self._limits},
                }
            raw = data.get("counts") or {}
            counts: dict[str, int] = {}
            for k in self._limits:
                try:
                    counts[k] = int(raw.get(k, 0))
                except (TypeError, ValueError):
                    counts[k] = 0
            return {"date": data["date"], "counts": counts}
        except (OSError, json.JSONDecodeError, ValueError):
            return {
                "date": _today(),
                "counts": {k: 0 for k in self._limits},
            }

    def _save(self) -> None:
        try:
            self._file.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            # 配额落盘失败不应该让请求失败；最坏情况下重新计数。
            pass

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def snapshot(self) -> QuotaSnapshot:
        with self._lock:
            self._maybe_reset()
            return self._build_snapshot()

    def increment(self, kind: QuotaKind = "search", n: int = 1) -> QuotaSnapshot:
        with self._lock:
            self._maybe_reset()
            self._state["counts"][kind] = self._state["counts"].get(kind, 0) + n
            self._save()
            return self._build_snapshot()

    def reset(self) -> None:
        """清零（CLI ``--reset-quota`` 用）。"""
        with self._lock:
            self._state = {
                "date": _today(),
                "counts": {k: 0 for k in self._limits},
            }
            self._save()

    @property
    def limit(self) -> int:
        """向后兼容：返回各接口上限的总和。"""
        return sum(self._limits.values())

    @property
    def limits(self) -> dict[QuotaKind, int]:
        return dict(self._limits)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _maybe_reset(self) -> None:
        if self._state.get("date") != _today():
            self._state = {
                "date": _today(),
                "counts": {k: 0 for k in self._limits},
            }

    def _build_snapshot(self) -> QuotaSnapshot:
        by_kind: dict[str, dict[str, int]] = {}
        for kind, limit in self._limits.items():
            used = int(self._state["counts"].get(kind, 0))
            by_kind[kind] = {
                "used": used,
                "limit": limit,
                "remaining": max(0, limit - used),
            }
        return QuotaSnapshot(by_kind=by_kind, reset_at=_next_reset_iso())


__all__ = [
    "QuotaTracker",
    "QuotaSnapshot",
    "QuotaKind",
    "DEFAULT_LIMITS",
    "DEFAULT_DAILY_LIMIT",
]
