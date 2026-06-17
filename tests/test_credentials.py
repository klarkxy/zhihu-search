"""Tests for credentials module."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from zhihu_search import credentials


GOOD_SECRET = "zh1_abcdefghijklmnop"  # 20 chars, matches hint regex


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect credential storage to a temp dir for every test."""
    monkeypatch.setenv("ZHIHU_SEARCH_HOME", str(tmp_path))
    monkeypatch.delenv(credentials.ENV_VAR, raising=False)


def test_save_then_load(tmp_path: Path) -> None:
    path = credentials.save(GOOD_SECRET)
    assert path.is_file()
    creds = credentials.load()
    assert creds.access_secret == GOOD_SECRET
    assert creds.source == "file"
    assert creds.path == path
    # POSIX-only chmod is best-effort, don't assert.


def test_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(credentials.ENV_VAR, GOOD_SECRET)
    creds = credentials.load()
    assert creds.access_secret == GOOD_SECRET
    assert creds.source == "env"


def test_env_overrides_file(monkeypatch: pytest.MonkeyPatch) -> None:
    credentials.save(GOOD_SECRET)
    other = "zh1_overrideoverride"
    monkeypatch.setenv(credentials.ENV_VAR, other)
    creds = credentials.load()
    assert creds.access_secret == other
    assert creds.source == "env"


def test_load_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(credentials.ENV_VAR, raising=False)
    with pytest.raises(credentials.CredentialsError):
        credentials.load()


def test_load_malformed_file(tmp_path: Path) -> None:
    credentials.credentials_file().write_text("not json", encoding="utf-8")
    with pytest.raises(credentials.CredentialsError):
        credentials.load()


def test_load_missing_field(tmp_path: Path) -> None:
    credentials.credentials_file().write_text(
        json.dumps({"other": "value"}), encoding="utf-8"
    )
    with pytest.raises(credentials.CredentialsError):
        credentials.load()


def test_save_rejects_garbage() -> None:
    with pytest.raises(credentials.CredentialsError):
        credentials.save("x")
    with pytest.raises(credentials.CredentialsError):
        credentials.save("")


def test_memory_source() -> None:
    creds = credentials.load(secret=GOOD_SECRET)
    assert creds.source == "memory"
    assert creds.access_secret == GOOD_SECRET


def test_clear(tmp_path: Path) -> None:
    path = credentials.save(GOOD_SECRET)
    assert path.is_file()
    assert credentials.clear() is True
    assert not path.is_file()
    assert credentials.clear() is False


def test_hint_ok() -> None:
    assert credentials.hint_ok(GOOD_SECRET) is True
    assert credentials.hint_ok("not-a-token") is False