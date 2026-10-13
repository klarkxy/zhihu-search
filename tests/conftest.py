"""全局测试配置：隔离凭证目录，避免读取或修改用户真实配置。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """每个测试用例使用独立的应用配置目录。"""
    monkeypatch.setenv("ZHIHU_SEARCH_HOME", str(tmp_path))


@pytest.fixture(autouse=True)
def _isolate_legacy_request_contracts(monkeypatch, request):
    if request.path.name.startswith("test_call_policy"):
        return
    from zhihu_search.call_policy import CallPolicy
    async def passthrough(self, path, body, quota, execute):
        return await execute()
    monkeypatch.setattr(CallPolicy, "run", passthrough)
