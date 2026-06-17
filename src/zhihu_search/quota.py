"""每日调用配额追踪。

知乎开放平台官方文档没明确返回 ``X-RateLimit-*`` 响应头，所以我们
本地维护一份「今日调用次数」统计，附在每次返回给 agent 的内容里。
这样 agent 能在接近上限时主动收敛行为。

存储位置：``~/.config/zhihu-search/quota.json``
覆盖位置：通过 ``ZHIHU_SEARCH_HOME`` 环境变量。
默认上限：通过 ``ZHIHU_DAILY_LIMIT`` 环境变量（默认 1000 次/天）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional


DEFAULT_DAILY_LIMIT = 1000
QUOTA_FILE = "quota.json"


def _today() -> str:
    return date.today().isoformat()


@dataclass
class QuotaSnapshot:
    """某次调用后的配额快照，跟随响应一起返回。"""

    used: int
    remaining: int
    limit: int
    reset_at: str  # ISO 时间，下一次刷新（次日 0 点）

    def to_line(self) -> str:
        """一行可读的进度文本，附加在工具返回文本末尾。"""
        return (
            f"配额：今日已用 {self.used}/{self.limit}，剩余 {self.remaining} 次"
            f"（{self.reset_at} 刷新）"
        )


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
    ) -> None:
        self._dir = base_dir or self._default_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / QUOTA_FILE
        self._limit = daily_limit or int(
            os.environ.get("ZHIHU_DAILY_LIMIT", str(DEFAULT_DAILY_LIMIT))
        )
        self._lock = Lock()
        self._state = self._load()

    @staticmethod
    def _default_dir() -> Path:
        override = os.environ.get("ZHIHU_SEARCH_HOME")
        return Path(override) if override else Path.home() / ".config" / "zhihu-search"

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if not self._file.is_file():
            return {"date": _today(), "count": 0}
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            if data.get("date") != _today():
                return {"date": _today(), "count": 0}
            return {"date": data["date"], "count": int(data.get("count", 0))}
        except (OSError, json.JSONDecodeError, ValueError):
            return {"date": _today(), "count": 0}

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
            used = self._state["count"]
            return QuotaSnapshot(
                used=used,
                remaining=max(0, self._limit - used),
                limit=self._limit,
                reset_at=self._next_reset_iso(),
            )

    def increment(self, n: int = 1) -> QuotaSnapshot:
        with self._lock:
            self._maybe_reset()
            self._state["count"] += n
            self._save()
            used = self._state["count"]
            return QuotaSnapshot(
                used=used,
                remaining=max(0, self._limit - used),
                limit=self._limit,
                reset_at=self._next_reset_iso(),
            )

    def reset(self) -> None:
        """清零（CLI `--reset-quota` 用）。"""
        with self._lock:
            self._state = {"date": _today(), "count": 0}
            self._save()

    @property
    def limit(self) -> int:
        return self._limit

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _maybe_reset(self) -> None:
        if self._state.get("date") != _today():
            self._state = {"date": _today(), "count": 0}

    def _next_reset_iso(self) -> str:
        # 次日 0 点（本地时区）
        from datetime import timedelta

        tomorrow = date.today() + timedelta(days=1)
        return f"{tomorrow.isoformat()}T00:00:00"


__all__ = ["QuotaTracker", "QuotaSnapshot", "DEFAULT_DAILY_LIMIT"]