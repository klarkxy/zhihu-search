"""Local request protection, shared with dsh-zhihu. This ledger is not a bill.

The directory mutex covers the fresh quota read and the complete request. No
automatic stale-lock reclamation: a killed owner must not permit a second call
while its upstream outcome is unknown. Neither secrets nor response data persist.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from .upstream.base import McpError

T = TypeVar("T")

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
                 directory: Path | None = None, lock_timeout: float = 30,
                 now: Callable[[], float] = time.time) -> None:
        paid = os.environ.get("ZHIHU_ALLOW_PAID", "false").lower()
        if allow_paid is None and paid not in ("true", "false", "1", "0"):
            raise CallBlocked("ZHIHU_ALLOW_PAID 必须是 true/false 或 1/0。")
        self.allow_paid = paid in ("true", "1") if allow_paid is None else allow_paid
        try:
            cap = int(os.environ.get("ZHIHU_DAILY_CALL_LIMIT", "100")) if daily_call_limit is None else daily_call_limit
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
            return {"version": 1, "day": self._day(), "calls": 0, "uncertain": {}, "free": {}}
        except (OSError, ValueError) as exc:
            raise CallBlocked("本地调用记录不可读；已阻止请求，请检查 call-policy/daily.json。") from exc
        if not isinstance(data, dict) or type(data.get("version")) is not int or data.get("version") != 1 or not isinstance(data.get("day"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["day"]) or not _integer(data.get("calls")) or not isinstance(data.get("uncertain"), dict) or any(not _integer(v) for v in data["uncertain"].values()):
            raise CallBlocked("本地调用记录无效；已阻止请求，不能自动清零。")
        if "free" not in data:
            data["free"] = {}  # Existing version-1 ledgers predate the quota floor.
        if not isinstance(data["free"], dict) or any(not _integer(v) for v in data["free"].values()):
            raise CallBlocked("本地免费预留记录无效；已阻止请求。")
        if data["day"] != self._day():
            data.update(day=self._day(), calls=0, free={})
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

    async def run(self, path: str, body: Any, quota: Callable[[str], Awaitable[Any]],
                  execute: Callable[[], Awaitable[T]]) -> T:
        group = quota_group(path, body)
        if self.allow_paid and not priced_capability(path, body):
            raise CallBlocked("付费调用已阻止：该能力的官方计费未确认；请使用免费保护模式。")
        lock = self.directory / "request.lock"
        acquired = False
        deadline = time.monotonic() + self.lock_timeout
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            while not acquired:
                try:
                    lock.mkdir()
                    acquired = True
                except FileExistsError:
                    if time.monotonic() >= deadline:
                        raise CallBlocked("本地保护锁忙或遗留；已阻止请求。确认两个客户端均无在途请求后再移除 call-policy/request.lock。")
                    await asyncio.sleep(0.05)
            data = self._read()
            if data["calls"] >= self.daily_call_limit:
                raise CallBlocked("已达到本地北京时间每日业务调用上限；额度查询仍可使用。")
            if not self.allow_paid:
                try:
                    rows = await quota(group)
                except Exception as exc:
                    raise CallBlocked("免费额度预查失败；未发送业务请求，请稍后手动查询官方额度。") from exc
                matches = [row for row in rows if isinstance(row, dict) and row.get("APIID") == group] if isinstance(rows, list) else []
                if len(matches) != 1 or not _integer(matches[0].get("RemainingQuota")):
                    raise CallBlocked("官方未返回有效的免费剩余额度；未发送业务请求。")
                available = min(matches[0]["RemainingQuota"] - data["uncertain"].get(group, 0), data["free"].get(group, matches[0]["RemainingQuota"]))
                if available <= 0:
                    raise CallBlocked("免费额度不足，或有结果未知的已发送请求；未发送业务请求。")
                data["free"][group] = available - 1
            elif group in data["free"]:
                data["free"][group] = max(0, data["free"][group] - 1)
            # Durable reservation before dispatch. Never refund uncertain outcomes.
            data["calls"] += 1
            data["uncertain"][group] = data["uncertain"].get(group, 0) + 1
            self._write(data)
            result = await execute()
            data["uncertain"][group] -= 1
            self._write(data)
            return result
        except OSError as exc:
            raise CallBlocked("本地保护存储不可用；已阻止业务请求。") from exc
        finally:
            if acquired:
                lock.rmdir()
