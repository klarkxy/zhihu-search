"""QuotaTracker 单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zhihu_search.quota import (
    DEFAULT_DAILY_LIMIT,
    DEFAULT_LIMITS,
    QuotaTracker,
)


@pytest.fixture
def tracker(tmp_path: Path) -> QuotaTracker:
    return QuotaTracker(
        base_dir=tmp_path,
        limits={"search": 10, "trending": 5, "ask": 3},
    )


def test_default_limits() -> None:
    """默认上限对得上知乎开发者后台的展示口径。"""
    assert DEFAULT_LIMITS == {"search": 5000, "trending": 100, "ask": 100}


def test_initial_snapshot_is_zero(tracker: QuotaTracker) -> None:
    snap = tracker.snapshot()
    assert snap.by_kind == {
        "search": {"used": 0, "limit": 10, "remaining": 10},
        "trending": {"used": 0, "limit": 5, "remaining": 5},
        "ask": {"used": 0, "limit": 3, "remaining": 3},
    }
    assert snap.reset_at.endswith("T00:00:00")


def test_increment_isolated_per_kind(tracker: QuotaTracker) -> None:
    """每个 kind 单独计数，互不影响。"""
    tracker.increment("search")
    tracker.increment("search")
    tracker.increment("trending")

    snap = tracker.snapshot()
    assert snap.by_kind["search"]["used"] == 2
    assert snap.by_kind["search"]["remaining"] == 8
    assert snap.by_kind["trending"]["used"] == 1
    assert snap.by_kind["trending"]["remaining"] == 4
    assert snap.by_kind["ask"]["used"] == 0


def test_persistence_across_instances(tmp_path: Path) -> None:
    t1 = QuotaTracker(
        base_dir=tmp_path,
        limits={"search": 10, "trending": 5, "ask": 3},
    )
    t1.increment("search", 3)
    t1.increment("trending", 2)
    t2 = QuotaTracker(
        base_dir=tmp_path,
        limits={"search": 10, "trending": 5, "ask": 3},
    )
    assert t2.snapshot().by_kind["search"]["used"] == 3
    assert t2.snapshot().by_kind["trending"]["used"] == 2


def test_remaining_floors_at_zero(tracker: QuotaTracker) -> None:
    for _ in range(15):
        tracker.increment("search")
    snap = tracker.snapshot()
    assert snap.by_kind["search"]["used"] == 15
    assert snap.by_kind["search"]["remaining"] == 0  # 不能为负


def test_reset_clears_all_kinds(tracker: QuotaTracker) -> None:
    tracker.increment("search", 5)
    tracker.increment("ask", 2)
    tracker.reset()
    snap = tracker.snapshot()
    assert snap.by_kind["search"]["used"] == 0
    assert snap.by_kind["ask"]["used"] == 0


def test_snapshot_line_format(tracker: QuotaTracker) -> None:
    tracker.increment("search", 3)
    tracker.increment("trending", 1)
    line = tracker.snapshot().to_line()
    assert "搜索 3/10" in line
    assert "热榜 1/5" in line
    assert "直答 0/3" in line
    assert "刷新" in line


def test_snapshot_line_marks_exhausted(tracker: QuotaTracker) -> None:
    for _ in range(3):
        tracker.increment("ask")
    line = tracker.snapshot().to_line()
    assert "直答 3/3" in line
    assert "已耗尽" in line


def test_different_day_resets(tmp_path: Path) -> None:
    """文件里的日期不是今天时，应自动重置。"""
    quota_file = tmp_path / "quota.json"
    quota_file.write_text(
        json.dumps(
            {
                "date": "2020-01-01",
                "counts": {"search": 999, "trending": 99, "ask": 99},
            }
        ),
        encoding="utf-8",
    )
    t = QuotaTracker(
        base_dir=tmp_path,
        limits={"search": 10, "trending": 5, "ask": 3},
    )
    assert t.snapshot().by_kind["search"]["used"] == 0


def test_default_env_legacy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """旧的 ``ZHIHU_DAILY_LIMIT`` 环境变量依然能起作用（向后兼容）。"""
    monkeypatch.setenv("ZHIHU_DAILY_LIMIT", "500")
    monkeypatch.delenv("ZHIHU_DAILY_LIMIT_SEARCH", raising=False)
    monkeypatch.delenv("ZHIHU_DAILY_LIMIT_TRENDING", raising=False)
    monkeypatch.delenv("ZHIHU_DAILY_LIMIT_ASK", raising=False)
    t = QuotaTracker(base_dir=tmp_path)
    assert t.limits == {"search": 500, "trending": 500, "ask": 500}


def test_per_kind_env_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """分接口环境变量会覆盖「统一变量」对应桶的值；未设的桶保留统一变量值。"""
    monkeypatch.setenv("ZHIHU_DAILY_LIMIT", "500")
    monkeypatch.setenv("ZHIHU_DAILY_LIMIT_SEARCH", "9999")
    monkeypatch.setenv("ZHIHU_DAILY_LIMIT_TRENDING", "10")
    monkeypatch.delenv("ZHIHU_DAILY_LIMIT_ASK", raising=False)
    t = QuotaTracker(base_dir=tmp_path)
    assert t.limits == {"search": 9999, "trending": 10, "ask": 500}


def test_limit_property_legacy_sum(tracker: QuotaTracker) -> None:
    """``limit`` 属性保留总和语义（旧代码兼容）。"""
    assert tracker.limit == 10 + 5 + 3


def test_used_property_legacy_sum(tracker: QuotaTracker) -> None:
    tracker.increment("search", 4)
    tracker.increment("ask", 2)
    assert tracker.snapshot().used == 6
