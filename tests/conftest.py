"""全局测试配置：隔离凭证目录，避免读取或修改用户真实配置。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """每个测试用例使用独立的应用配置目录。"""
    monkeypatch.setenv("ZHIHU_SEARCH_HOME", str(tmp_path))
