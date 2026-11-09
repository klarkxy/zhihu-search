"""本地同步草稿。只放在配置目录，不写入当前仓库。"""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .. import credentials

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


def _now() -> float:
    return time.time()


def store_path() -> Path:
    return credentials.credentials_dir() / "sync-store.json"


def beijing_day(now: float | None = None) -> str:
    moment = datetime.fromtimestamp(now if now is not None else _now(), timezone(timedelta(hours=8)))
    return moment.date().isoformat()


def publish_limit() -> int:
    raw = os.environ.get("ZHIHU_SYNC_DAILY_PUBLISH_LIMIT", "50")
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("ZHIHU_SYNC_DAILY_PUBLISH_LIMIT 必须是 1 到 50 的整数。") from exc
    if not 1 <= value <= 50:
        raise RuntimeError("ZHIHU_SYNC_DAILY_PUBLISH_LIMIT 必须是 1 到 50 的整数。")
    return value


@contextmanager
def locked_store() -> Iterator[dict[str, object]]:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            payload = _read(path)
            yield payload
            _write(path, payload)
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def read_store() -> dict[str, object]:
    return _read(store_path())


def new_id() -> str:
    return uuid.uuid4().hex


def _read(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"drafts": {}, "reviews": {}, "publish_attempts": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("同步草稿文件已损坏，已停止以免丢稿或重复发布。") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("同步草稿文件已损坏，已停止以免丢稿或重复发布。")
    payload.setdefault("drafts", {})
    payload.setdefault("reviews", {})
    payload.setdefault("publish_attempts", {})
    return payload


def _write(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:  # pragma: no cover - Windows
        pass
    temporary.replace(path)
