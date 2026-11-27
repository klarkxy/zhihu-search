"""Local request protection, shared with dsh-zhihu. This ledger is not a bill.

The directory mutex covers only ledger read-modify-write and, when needed, the
official quota precheck. Upstream business requests run outside the mutex. Lock
ownership is recorded in a sibling file so a crashed owner can be reclaimed by
age without inspecting or terminating its process. Neither secrets nor response
data persist.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import stat
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from .upstream.base import McpError

T = TypeVar("T")

QUOTA_CHECK_TTL = 300
QUOTA_CHECK_MIN_REMAINING = 20
QUOTA_PRECHECK_TIMEOUT = 10
LOCK_STALE_AFTER = 60
LOCK_WAIT_TIMEOUT = 75

# Official quota mappings. Price confirmation is required only in paid mode.
QUOTA_GROUPS = {
    "/api/v1/content/zhihu_search": "zhihu_search",
    "/api/v1/content/global_search": "global_search",
    "/api/v1/content/hot_list": "hot_list",
    "/api/v1/content/question_answers": "question_discovery",
    "/api/v1/user/contents": "user_data",
    "/api/v1/user/followees": "user_data",
    "/api/v1/user/collections": "user_data",
    "/api/v1/user/favlists": "user_data",
    "/api/v1/user/favlist_contents": "user_data",
    "/api/v1/user/content_detail": "creator",
    "/api/v1/user/content_comments": "creator",
    "/api/v1/user/creator_account_stats": "creator",
    "/api/v1/user/creator_content_stats": "creator",
    "/api/v1/knowledge/bases": "knowledge",
    "/api/v1/knowledge/files": "knowledge",
    "/api/v1/knowledge/search": "knowledge",
}


PRICED_PATHS = frozenset(QUOTA_GROUPS)
QUOTA_GROUPS["/api/v1/user/question_recommendations"] = "question_discovery"


def priced_capability(path: str, body: Any) -> bool:
    return path in PRICED_PATHS or (path.startswith("/api/v1/knowledge/bases/") and path.endswith("/items")) or (path == "/v1/chat/completions" and isinstance(body, dict) and body.get("model") == "zhida-agent")


class CallBlocked(McpError):
    code = -32007


def quota_group(path: str, body: Any) -> str:
    if path == "/v1/chat/completions" and isinstance(body, dict) and body.get("model") in ("zhida-agent", "zhida-fast-1p5", "zhida-thinking-1p5"):
        return "zhida_openai"
    if path.startswith("/api/v1/knowledge/bases/") and path.endswith("/items"):
        return "knowledge"
    if path == "/api/v1/pdf-parse/tasks" or path.startswith("/api/v1/pdf-parse/tasks/") or path == "/api/v1/ppt-generation/tasks" or path.startswith("/api/v1/ppt-generation/tasks/"):
        return "tools"
    group = QUOTA_GROUPS.get(path)
    if group is None:
        raise CallBlocked("调用已阻止：该能力的官方额度映射未确认；不能擅自套价。")
    return group


def _integer(value: Any) -> bool:
    return type(value) is int and 0 <= value <= 9007199254740991


class CallPolicy:
    def __init__(self, *, allow_paid: bool | None = None, daily_call_limit: int | None = None,
                 directory: Path | None = None, lock_timeout: float = LOCK_WAIT_TIMEOUT,
                 now: Callable[[], float] = time.time) -> None:
        paid = os.environ.get("ZHIHU_ALLOW_PAID", "false").lower()
        if allow_paid is None and paid not in ("true", "false", "1", "0"):
            raise CallBlocked("ZHIHU_ALLOW_PAID 必须是 true/false 或 1/0。")
        self.allow_paid = paid in ("true", "1") if allow_paid is None else allow_paid
        try:
            cap = int(os.environ.get("ZHIHU_DAILY_CALL_LIMIT", "1000")) if daily_call_limit is None else daily_call_limit
        except ValueError as exc:
            raise CallBlocked("每日调用上限必须是 1-100000 的整数。") from exc
        if type(self.allow_paid) is not bool or type(cap) is not int or not 1 <= cap <= 100000:
            raise CallBlocked("付费开关必须是布尔值，每日调用上限必须是 1-100000 的整数。")
        self.daily_call_limit = cap
        base = Path(os.environ.get("ZHIHU_SEARCH_HOME") or Path.home() / ".config" / "zhihu-search")
        self.directory = directory or Path(os.environ.get("ZHIHU_CALL_POLICY_DIR") or base / "call-policy")
        self.lock_timeout = lock_timeout
        self.now = now

    def _day(self) -> str:
        return datetime.fromtimestamp(self.now(), timezone(timedelta(hours=8))).date().isoformat()

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads((self.directory / "daily.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 1, "day": self._day(), "calls": 0, "uncertain": {}, "free": {}, "checked": {}}
        except (OSError, ValueError) as exc:
            raise CallBlocked("本地调用记录不可读；已阻止请求，请检查 call-policy/daily.json。") from exc
        if not isinstance(data, dict) or type(data.get("version")) is not int or data.get("version") != 1 or not isinstance(data.get("day"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["day"]) or not _integer(data.get("calls")) or not isinstance(data.get("uncertain"), dict) or any(not _integer(v) for v in data["uncertain"].values()):
            raise CallBlocked("本地调用记录无效；已阻止请求，不能自动清零。")
        if "free" not in data:
            data["free"] = {}  # Existing version-1 ledgers predate the quota floor.
        if not isinstance(data["free"], dict) or any(not _integer(v) for v in data["free"].values()):
            raise CallBlocked("本地免费预留记录无效；已阻止请求。")
        if "checked" not in data:
            data["checked"] = {}  # Existing version-1 ledgers predate quota-check caching.
        if not isinstance(data["checked"], dict) or any(not _integer(v) for v in data["checked"].values()):
            raise CallBlocked("本地额度预查记录无效；已阻止请求。")
        if "credential" in data and data["credential"] is not None and (not isinstance(data["credential"], str) or not data["credential"]):
            raise CallBlocked("本地凭证摘要记录无效；已阻止请求。")
        if data["day"] != self._day():
            data.update(day=self._day(), calls=0, uncertain={}, free={}, checked={})
        return data

    def _write(self, data: dict[str, Any]) -> None:
        temporary = self.directory / ("daily-" + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / "daily.json")
        except OSError as exc:
            raise CallBlocked("本地调用记录保存失败；已阻止请求。") from exc
        finally:
            temporary.unlink(missing_ok=True)

    @property
    def _lock(self) -> Path:
        return self.directory / "request.lock"

    @property
    def _owner(self) -> Path:
        return self.directory / "request.lock.owner.json"

    @property
    def _reclaim(self) -> Path:
        return self.directory / "request.lock.reclaim"

    def _write_owner(self, token: str) -> None:
        temporary = self.directory / ("owner-" + uuid.uuid4().hex + ".tmp")
        payload = {"token": token, "pid": os.getpid(), "acquiredAt": int(self.now() * 1000)}
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._owner)
        finally:
            temporary.unlink(missing_ok=True)

    def _lock_age(self) -> float | None:
        try:
            lock_stat = self._lock.stat()
        except FileNotFoundError:
            return None
        basis = lock_stat.st_mtime
        try:
            owner_stat = self._owner.stat()
            owner = json.loads(self._owner.read_text(encoding="utf-8"))
            acquired = owner.get("acquiredAt") if isinstance(owner, dict) else None
            if type(acquired) in (int, float) and math.isfinite(acquired):
                acquired_seconds = acquired / 1000
                # An owner file older than this lock directory belongs to a
                # previous incarnation and must not make a fresh lock look stale.
                if owner_stat.st_mtime >= lock_stat.st_mtime - 0.002:
                    basis = acquired_seconds
        except (OSError, ValueError):
            pass
        return self.now() - basis

    def _acquire_reclaim(self, *, attempts: int = 2, retry_delay: float = 0.0) -> bool:
        reclaim = self._reclaim
        for attempt in range(attempts):
            try:
                reclaim.mkdir()
                return True
            except FileExistsError:
                try:
                    reclaim_stat = reclaim.stat()
                except FileNotFoundError:
                    continue
                if stat.S_ISDIR(reclaim_stat.st_mode) and self.now() - reclaim_stat.st_mtime > LOCK_STALE_AFTER:
                    try:
                        reclaim.rmdir()
                    except OSError:
                        pass
                    continue
                if retry_delay > 0 and attempt + 1 < attempts:
                    time.sleep(retry_delay)
                    continue
                return False
        return False

    def _reclaim_stale_lock(self) -> bool:
        if not self._acquire_reclaim(attempts=2):
            return False
        try:
            age = self._lock_age()
            if age is None or age <= LOCK_STALE_AFTER:
                return False
            try:
                lock_stat = self._lock.stat()
            except FileNotFoundError:
                return False
            if not stat.S_ISDIR(lock_stat.st_mode):
                return False
            # Remove the old owner before renaming. While request.lock exists no
            # new owner can be created; this avoids deleting a successor's owner.
            try:
                self._owner.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                return False
            stale = self.directory / ("request.lock.stale-" + uuid.uuid4().hex)
            try:
                self._lock.rename(stale)
            except OSError:
                return False
            try:
                stale.rmdir()
            except OSError:
                pass
            return True
        finally:
            try:
                self._reclaim.rmdir()
            except OSError:
                pass

    async def _acquire(self) -> str:
        token = uuid.uuid4().hex
        deadline = time.monotonic() + self.lock_timeout
        self.directory.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self._lock.mkdir()
            except FileExistsError:
                age = self._lock_age()
                if age is not None and age > LOCK_STALE_AFTER and self._reclaim_stale_lock():
                    continue
                if time.monotonic() >= deadline:
                    raise CallBlocked("本地保护锁忙；已阻止请求。遗留锁会在 60 秒后自动恢复。")
                await asyncio.sleep(0.05)
            else:
                try:
                    self._write_owner(token)
                except Exception:
                    try:
                        self._lock.rmdir()
                    except OSError:
                        pass
                    raise
                return token

    def _release(self, token: str) -> None:
        try:
            if not self._acquire_reclaim(attempts=40, retry_delay=0.005):
                return
            try:
                try:
                    owner = json.loads(self._owner.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return
                if not isinstance(owner, dict) or owner.get("token") != token:
                    return
                self._owner.unlink(missing_ok=True)
                self._lock.rmdir()
            finally:
                try:
                    self._reclaim.rmdir()
                except OSError:
                    pass
        except Exception:
            pass

    async def _reserve(self, group: str, quota: Callable[[str], Awaitable[Any]], *,
                       credential: str | None = None) -> None:
        if credential is not None and not isinstance(credential, str):
            raise CallBlocked("凭证摘要无效；已阻止请求。")
        token = await self._acquire()
        try:
            data = self._read()
            if data["calls"] >= self.daily_call_limit:
                raise CallBlocked("已达到本地北京时间每日业务调用上限；额度查询仍可使用。")
            if credential:
                previous_credential = data.get("credential")
                if previous_credential is not None and previous_credential != credential:
                    data["free"] = {}
                    data["checked"] = {}
                    data["uncertain"] = {}
                data["credential"] = credential
            if not self.allow_paid:
                now_seconds = int(self.now())
                checked = data["checked"].get(group)
                floor = data["free"].get(group)
                cached = checked is not None and now_seconds - checked < QUOTA_CHECK_TTL and floor is not None and floor >= QUOTA_CHECK_MIN_REMAINING
                if cached:
                    available = floor
                    next_free = floor - 1
                else:
                    try:
                        rows = await asyncio.wait_for(quota(group), QUOTA_PRECHECK_TIMEOUT)
                    except Exception as exc:
                        raise CallBlocked("免费额度预查失败；未发送业务请求，请稍后手动查询官方额度。") from exc
                    matches = [row for row in rows if isinstance(row, dict) and row.get("APIID") == group] if isinstance(rows, list) else []
                    if len(matches) != 1 or not _integer(matches[0].get("RemainingQuota")):
                        raise CallBlocked("官方未返回有效的免费剩余额度；未发送业务请求。")
                    remaining = matches[0]["RemainingQuota"]
                    prev_free = data["free"].get(group, remaining)
                    uncertain = data["uncertain"].get(group, 0)
                    base_free = min(remaining, prev_free)
                    data["checked"][group] = now_seconds
                    available = base_free - uncertain
                    next_free = base_free - 1
                if available <= 0:
                    raise CallBlocked("免费额度不足，或有结果未知的已发送请求；未发送业务请求。")
                data["free"][group] = next_free
            elif group in data["free"]:
                data["free"][group] = max(0, data["free"][group] - 1)
            # Durable reservation before dispatch. Never refund uncertain outcomes.
            data["calls"] += 1
            data["uncertain"][group] = data["uncertain"].get(group, 0) + 1
            self._write(data)
        finally:
            self._release(token)

    async def _settle(self, group: str) -> None:
        try:
            token = await self._acquire()
        except Exception:
            return
        try:
            try:
                data = self._read()
                data["uncertain"][group] = max(0, data["uncertain"].get(group, 0) - 1)
                self._write(data)
            except Exception:
                pass
        finally:
            self._release(token)

    async def run(self, path: str, body: Any, quota: Callable[[str], Awaitable[Any]],
                  execute: Callable[[], Awaitable[T]], *, credential: str | None = None) -> T:
        group = quota_group(path, body)
        if self.allow_paid and not priced_capability(path, body):
            raise CallBlocked("付费调用已阻止：该能力的官方计费未确认；请使用免费保护模式。")
        try:
            await self._reserve(group, quota, credential=credential)
        except OSError as exc:
            raise CallBlocked("本地保护存储不可用；已阻止业务请求。") from exc
        result = await execute()
        # Settlement is best-effort: the upstream call has already succeeded
        # and a local lock/IO problem must not turn that result into a failure.
        await self._settle(group)
        return result
