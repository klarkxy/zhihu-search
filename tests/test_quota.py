"""QuotaTracker / CircuitBreaker 单元测试。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from zhihu_search.quota import (
    CircuitBreaker,
    QuotaTracker,
)


@pytest.fixture
def tracker(tmp_path: Path) -> QuotaTracker:
    return QuotaTracker(base_dir=tmp_path)


# ---------------------------------------------------------------------------
# QuotaTracker — 计数
# ---------------------------------------------------------------------------


def test_initial_snapshot_is_zero(tracker: QuotaTracker) -> None:
    snap = tracker.snapshot()
    assert snap.by_kind == {
        "search": {"used": 0},
        "trending": {"used": 0},
        "ask": {"used": 0},
    }
    assert snap.reset_at.endswith("T00:00:00")


def test_increment_isolated_per_kind(tracker: QuotaTracker) -> None:
    """每个 kind 单独计数，互不影响。"""
    tracker.increment("search")
    tracker.increment("search")
    tracker.increment("trending")

    snap = tracker.snapshot()
    assert snap.by_kind["search"]["used"] == 2
    assert snap.by_kind["trending"]["used"] == 1
    assert snap.by_kind["ask"]["used"] == 0


def test_persistence_across_instances(tmp_path: Path) -> None:
    t1 = QuotaTracker(base_dir=tmp_path)
    t1.increment("search", 3)
    t1.increment("trending", 2)
    t2 = QuotaTracker(base_dir=tmp_path)
    assert t2.snapshot().by_kind["search"]["used"] == 3
    assert t2.snapshot().by_kind["trending"]["used"] == 2


def test_reset_clears_all_kinds(tracker: QuotaTracker) -> None:
    tracker.increment("search", 5)
    tracker.increment("ask", 2)
    tracker.reset()
    snap = tracker.snapshot()
    assert snap.by_kind["search"]["used"] == 0
    assert snap.by_kind["ask"]["used"] == 0


def test_used_property_sum(tracker: QuotaTracker) -> None:
    tracker.increment("search", 4)
    tracker.increment("ask", 2)
    assert tracker.snapshot().used == 6


def test_to_line_format(tracker: QuotaTracker) -> None:
    tracker.increment("search", 3)
    tracker.increment("trending", 1)
    line = tracker.snapshot().to_line()
    assert "搜索 3" in line
    assert "热榜 1" in line
    assert "直答 0" in line
    # 不应包含 "已耗尽"（旧版用词）
    assert "已耗尽" not in line


def test_different_day_resets(tmp_path: Path) -> None:
    """文件里的日期不是今天时，应自动重置。"""
    quota_file = tmp_path / "quota.json"
    quota_file.write_text(
        json.dumps(
            {"date": "2020-01-01", "counts": {"search": 999, "trending": 99, "ask": 99}}
        ),
        encoding="utf-8",
    )
    t = QuotaTracker(base_dir=tmp_path)
    assert t.snapshot().by_kind["search"]["used"] == 0


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker()
        assert cb.is_allowed() is True
        assert cb.info().state == "closed"

    def test_trips_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
        assert cb.is_allowed() is True

        cb.record_failure()  # 1/2
        assert cb.is_allowed() is True  # 未达阈值

        cb.record_failure()  # 2/2 → OPEN
        assert cb.is_allowed() is False
        assert cb.info().state == "open"

    def test_single_failure_with_threshold_1(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
        assert cb.is_allowed() is True
        cb.record_failure()
        assert cb.is_allowed() is False

    def test_half_open_transition_on_expiry(self):
        """冷却时间过后应进入 HALF_OPEN，允许一次请求。"""
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
        cb.record_failure()
        assert cb.is_allowed() is False  # OPEN

        time.sleep(0.06)
        assert cb.is_allowed() is True  # HALF_OPEN
        assert cb.info().state == "half_open"

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
        cb.record_failure()
        time.sleep(0.06)

        assert cb.is_allowed() is True  # HALF_OPEN
        cb.record_success()
        assert cb.is_allowed() is True  # CLOSED
        assert cb.info().state == "closed"

    def test_half_open_failure_reopens(self):
        """HALF_OPEN 状态下再次失败 → 回到 OPEN。"""
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
        cb.record_failure()
        time.sleep(0.06)

        cb.is_allowed()  # → HALF_OPEN
        cb.record_failure()  # → OPEN (half_open 再限流直接跳 open)
        assert cb.is_allowed() is False
        assert cb.info().state == "open"

    def test_success_resets_failure_count(self):
        """成功应清零失败计数，即使未达阈值。"""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # 清零
        assert cb.is_allowed() is True

        # 再失败一次—应只算 1/3
        cb.record_failure()
        assert cb.is_allowed() is True  # 1/3，仍允许

    def test_remaining_cooldown(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=30)
        cb.record_failure()
        info = cb.info()
        assert info.state == "open"
        assert info.remaining_cooldown > 0
        assert info.remaining_cooldown <= 30

    def test_no_remaining_when_closed(self):
        cb = CircuitBreaker()
        assert cb.info().remaining_cooldown == 0

    def test_reset_clears_state(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=999)
        cb.record_failure()
        assert cb.info().state == "open"
        cb.reset()
        assert cb.info().state == "closed"
        assert cb.is_allowed() is True

    def test_concurrent_safety(self):
        """熔断器是线程安全的；多次并发调用不崩。"""
        import threading

        cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=60)
        errors = []

        def worker():
            try:
                cb.is_allowed()
                cb.record_failure()
                cb.record_success()
                cb.info()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ---------------------------------------------------------------------------
# QuotaTracker — 熔断集成
# ---------------------------------------------------------------------------


def test_breaker_integration_via_tracker(tracker: QuotaTracker) -> None:
    """QuotaTracker 的熔断方法应与 CircuitBreaker 联动。"""
    assert tracker.is_allowed("search") is True

    # 模拟两次限流失败
    tracker.record_failure("search")
    tracker.record_failure("search")
    # 第三次检查应返回 False
    assert tracker.is_allowed("search") is False

    # 热榜不受影响
    assert tracker.is_allowed("trending") is True

    # reset 应清理熔断状态
    tracker.reset()
    assert tracker.is_allowed("search") is True


def test_breaker_info_in_snapshot(tracker: QuotaTracker) -> None:
    """快照里应包含熔断状态。"""
    snap = tracker.snapshot()
    assert "search" in snap.breakers
    assert snap.breakers["search"].state == "closed"
    assert snap.breakers["search"].remaining_cooldown == 0

    tracker.record_failure("ask")
    tracker.record_failure("ask")
    snap2 = tracker.snapshot()
    assert snap2.breakers["ask"].state == "open"
    assert snap2.breakers["ask"].remaining_cooldown > 0
    assert snap2.breakers["search"].state == "closed"  # 不受影响


def test_to_line_with_breaker(tracker: QuotaTracker) -> None:
    """熔断时应显示警告行。"""
    tracker.increment("search", 5)
    tracker.record_failure("search")
    tracker.record_failure("search")  # → OPEN

    line = tracker.snapshot().to_line()
    assert "今日调用：" in line
    assert "搜索 5" in line
    assert "已熔断" in line
    assert "冷却剩余" in line
