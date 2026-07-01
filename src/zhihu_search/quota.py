"""每日调用追踪与熔断保护。

知乎开放平台官方文档没有明确返回 ``X-RateLimit-*`` 响应头，所以我们
本地维护一份「今日调用次数」统计，附在每次返回里供参考。

**核心机制是熔断保护**：不同账号的额度差异很大，硬编码上限没有参考价值。
当某个接口被限流（RateLimited）时，我们启动熔断器，在一段时间内拒绝该
接口的所有请求，冷却结束后自动恢复。

计数按「接口类别」分开维护（与知乎开发者后台展示口径一致）：
- ``search`` ：知乎搜索 + 全网搜索
- ``trending``：热榜
- ``ask``    ：直答（含 fast / thinking / agent 三个模型）

存储位置：``~/.config/zhihu-search/quota.json``
覆盖位置：通过 ``ZHIHU_SEARCH_HOME`` 环境变量。
"""

from __future__ import annotations

import json
import os
import time as _time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from threading import Lock
from typing import Literal, Optional


QuotaKind = Literal["search", "trending", "ask"]

_QUOTA_FILE = "quota.json"

_KIND_LABELS: dict[str, str] = {
    "search": "搜索",
    "trending": "热榜",
    "ask": "直答",
}

# ---------------------------------------------------------------------------
# 熔断器
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BreakerInfo:
    """熔断器状态快照，用于展示。"""

    #: "closed" | "open" | "half_open"
    state: str
    #: 尚需冷却秒数（state 为 open 时有效）
    remaining_cooldown: float


class CircuitBreaker:
    """按接口类别独立工作的熔断器。

    状态机：
        CLOSED ──(连续 failure_threshold 次限流)──▶ OPEN
        OPEN ──(cooldown_seconds 过期)──▶ HALF_OPEN
        HALF_OPEN ──(成功)──▶ CLOSED
        HALF_OPEN ──(再次限流)──▶ OPEN

    线程安全（Lock）。
    """

    def __init__(
        self,
        failure_threshold: int = 2,
        cooldown_seconds: int = 21600,  # 6 小时：按每日配额尺度冷却
    ) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._lock = Lock()
        self._state = "closed"
        self._failures = 0
        self._last_failure_at: float | None = None

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def is_allowed(self) -> bool:
        """请求是否允许发出？False 表示应直接拒绝。"""
        with self._lock:
            self._maybe_half_open()
            return self._state != "open"

    def record_failure(self) -> None:
        """记录一次限流失败。"""
        with self._lock:
            self._failures += 1
            self._last_failure_at = _time.monotonic()
            if self._state == "half_open" or self._failures >= self._threshold:
                self._state = "open"

    def record_success(self) -> None:
        """记录一次调用成功（清除半开状态）。"""
        with self._lock:
            if self._state == "half_open":
                self._state = "closed"
            self._failures = 0
            self._last_failure_at = None

    def info(self) -> BreakerInfo:
        """当前状态快照。"""
        with self._lock:
            self._maybe_half_open()
            remaining = 0.0
            if self._state == "open" and self._last_failure_at is not None:
                elapsed = _time.monotonic() - self._last_failure_at
                remaining = max(0.0, self._cooldown - elapsed)
            return BreakerInfo(state=self._state, remaining_cooldown=remaining)

    def reset(self) -> None:
        """强制重置熔断器（CLI ``--reset-quota`` 时一并清理）。"""
        with self._lock:
            self._state = "closed"
            self._failures = 0
            self._last_failure_at = None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _maybe_half_open(self) -> None:
        if self._state == "open" and self._last_failure_at is not None:
            if _time.monotonic() - self._last_failure_at >= self._cooldown:
                self._state = "half_open"


# ---------------------------------------------------------------------------
# 配额快照
# ---------------------------------------------------------------------------


@dataclass
class QuotaSnapshot:
    """某次调用后的配额+熔断快照，跟随响应一起返回。

    ``by_kind`` 只保留调用次数（不再展示硬编码上限）。
    """

    by_kind: dict[str, dict[str, int]] = field(default_factory=dict)
    reset_at: str = ""
    breakers: dict[str, BreakerInfo] = field(default_factory=dict)

    @property
    def used(self) -> int:
        return sum(item["used"] for item in self.by_kind.values())

    def to_line(self) -> str:
        """一行文本，附加在工具返回末尾。

        正常情况：
            今日调用：搜索 12 · 热榜 1 · 直答 0

        熔断时追加警告行：
            今日调用：搜索 12 · 热榜 1 · 直答 0
            ⚠ 搜索已熔断（冷却剩余 95 秒）
        """
        parts: list[str] = []
        for kind, info in self.by_kind.items():
            label = _KIND_LABELS.get(kind, kind)
            parts.append(f"{label} {info['used']}")
        summary = " · ".join(parts) if parts else "（无记录）"
        line = f"今日调用：{summary}"

        warnings: list[str] = []
        for kind, brk in (self.breakers or {}).items():
            if brk.state == "open":
                label = _KIND_LABELS.get(kind, kind)
                secs = int(brk.remaining_cooldown)
                warnings.append(f"{label} 已熔断（冷却剩余 {secs} 秒）")

        if warnings:
            line += "\n⚠ " + " · ".join(warnings)
        return line

    def to_block(self) -> str:
        """多行版，CLI ``--quota`` / 调试用。"""
        lines: list[str] = ["今日调用量："]
        for kind, info in self.by_kind.items():
            label = _KIND_LABELS.get(kind, kind)
            lines.append(f"  {label}  {info['used']} 次")

        breaker_lines: list[str] = []
        for kind, brk in (self.breakers or {}).items():
            label = _KIND_LABELS.get(kind, kind)
            if brk.state == "open":
                secs = int(brk.remaining_cooldown)
                breaker_lines.append(f"  {label}  ⚠ 已熔断（冷却剩余 {secs} 秒）")
            elif brk.state == "half_open":
                breaker_lines.append(f"  {label}  ⚡ 半开")
            else:
                breaker_lines.append(f"  {label}  正常")

        if breaker_lines:
            lines.append("")
            lines.append("熔断状态：")
            lines.extend(breaker_lines)

        return "\n".join(lines) if lines else "（无记录）"


# ---------------------------------------------------------------------------
# 配额追踪器
# ---------------------------------------------------------------------------


class QuotaTracker:
    """进程内 + 文件双层计数的配额追踪器 + 熔断器。

    - 进程内：``asyncio`` 任务安全（``threading.Lock``）
    - 文件：每次 ``increment`` 后立即落盘，重启后延续
    - 熔断：每个接口类别一个 ``CircuitBreaker``
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
    ) -> None:
        self._dir = base_dir or self._default_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / _QUOTA_FILE
        self._lock = Lock()
        self._state = self._load()
        # 熔断器（每个 kind 独立）
        self._breakers: dict[QuotaKind, CircuitBreaker] = {
            k: CircuitBreaker() for k in ("search", "trending", "ask")
        }

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    @staticmethod
    def _default_dir() -> Path:
        override = os.environ.get("ZHIHU_SEARCH_HOME")
        return Path(override) if override else Path.home() / ".config" / "zhihu-search"

    def _load(self) -> dict:
        if not self._file.is_file():
            return {"date": _today(), "counts": {"search": 0, "trending": 0, "ask": 0}}
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            if data.get("date") != _today():
                return {"date": _today(), "counts": {"search": 0, "trending": 0, "ask": 0}}
            raw = data.get("counts") or {}
            counts: dict[str, int] = {}
            for k in ("search", "trending", "ask"):
                try:
                    counts[k] = int(raw.get(k, 0))
                except (TypeError, ValueError):
                    counts[k] = 0
            return {"date": data["date"], "counts": counts}
        except (OSError, json.JSONDecodeError, ValueError):
            return {"date": _today(), "counts": {"search": 0, "trending": 0, "ask": 0}}

    def _save(self) -> None:
        try:
            self._file.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass  # 落盘失败不应让请求失败

    # ------------------------------------------------------------------
    # 配额 API
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
        """清零计数 + 重置所有熔断器（CLI ``--reset-quota`` 用）。"""
        with self._lock:
            self._state = {
                "date": _today(),
                "counts": {"search": 0, "trending": 0, "ask": 0},
            }
            self._save()
        for brk in self._breakers.values():
            brk.reset()

    # ------------------------------------------------------------------
    # 熔断 API
    # ------------------------------------------------------------------

    def is_allowed(self, kind: QuotaKind) -> bool:
        """检查可否发请求（熔断关闭 = 允许）。"""
        return self._breakers[kind].is_allowed()

    def record_failure(self, kind: QuotaKind) -> None:
        """记录一次限流失败（触发熔断器计数）。"""
        self._breakers[kind].record_failure()

    def record_success(self, kind: QuotaKind) -> None:
        """记录一次调用成功（复位熔断器）。"""
        self._breakers[kind].record_success()

    def breaker_info(self, kind: QuotaKind) -> BreakerInfo:
        """查询指定接口的熔断器状态。"""
        return self._breakers[kind].info()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _maybe_reset(self) -> None:
        if self._state.get("date") != _today():
            self._state = {
                "date": _today(),
                "counts": {"search": 0, "trending": 0, "ask": 0},
            }

    def _build_snapshot(self) -> QuotaSnapshot:
        by_kind: dict[str, dict[str, int]] = {}
        for kind in ("search", "trending", "ask"):
            used = int(self._state["counts"].get(kind, 0))
            by_kind[kind] = {"used": used}
        return QuotaSnapshot(
            by_kind=by_kind,
            reset_at=_next_reset_iso(),
            breakers={k: v.info() for k, v in self._breakers.items()},
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    return date.today().isoformat()


def _next_reset_iso() -> str:
    tomorrow = date.today() + timedelta(days=1)
    return f"{tomorrow.isoformat()}T00:00:00"


__all__ = [
    "QuotaTracker",
    "QuotaSnapshot",
    "CircuitBreaker",
    "BreakerInfo",
    "QuotaKind",
]
