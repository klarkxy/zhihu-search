"""QuotaTracker 单元测试。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from zhihu_search.quota import DEFAULT_DAILY_LIMIT, QuotaTracker


@pytest.fixture
def tracker(tmp_path: Path) -> QuotaTracker:
    return QuotaTracker(base_dir=tmp_path, daily_limit=10)


def test_initial_snapshot_is_zero(tracker: QuotaTracker) -> None:
    snap = tracker.snapshot()
    assert snap.used == 0
    assert snap.remaining == 10
    assert snap.limit == 10


def test_increment(tracker: QuotaTracker) -> None:
    snap = tracker.increment()
    assert snap.used == 1
    assert snap.remaining == 9


def test_persistence_across_instances(tmp_path: Path) -> None:
    t1 = QuotaTracker(base_dir=tmp_path, daily_limit=10)
    t1.increment(3)
    # 新实例应读到持久化计数
    t2 = QuotaTracker(base_dir=tmp_path, daily_limit=10)
    assert t2.snapshot().used == 3


def test_remaining_floors_at_zero(tracker: QuotaTracker) -> None:
    for _ in range(15):
        tracker.increment()
    snap = tracker.snapshot()
    assert snap.used == 15
    assert snap.remaining == 0  # 不能为负


def test_reset_clears(tracker: QuotaTracker) -> None:
    tracker.increment(5)
    tracker.reset()
    assert tracker.snapshot().used == 0


def test_snapshot_line_format(tracker: QuotaTracker) -> None:
    tracker.increment(3)
    line = tracker.snapshot().to_line()
    assert "已用 3/10" in line
    assert "剩余 7" in line
    assert "刷新" in line


def test_different_day_resets(tmp_path: Path) -> None:
    """文件里的日期不是今天时，应自动重置。"""
    quota_file = tmp_path / "quota.json"
    quota_file.write_text(
        json.dumps({"date": "2020-01-01", "count": 999}), encoding="utf-8"
    )
    t = QuotaTracker(base_dir=tmp_path, daily_limit=10)
    assert t.snapshot().used == 0


def test_default_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ZHIHU_DAILY_LIMIT", raising=False)
    t = QuotaTracker(base_dir=tmp_path)
    assert t.limit == DEFAULT_DAILY_LIMIT


def test_env_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZHIHU_DAILY_LIMIT", "500")
    t = QuotaTracker(base_dir=tmp_path)
    assert t.limit == 500