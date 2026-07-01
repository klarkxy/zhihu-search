"""全局测试配置：隔离配额文件到临时目录，避免影响或依赖真实 ~/.config/zhihu-search/。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_quota_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """每个测试用例使用独立的配额目录。"""
    monkeypatch.setenv("ZHIHU_SEARCH_HOME", str(tmp_path))
