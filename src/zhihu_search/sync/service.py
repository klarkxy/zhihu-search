"""草稿保存、校验、预览和确认后发布。"""

from __future__ import annotations

import base64
import secrets
from pathlib import Path
from typing import Mapping

import httpx

from .. import credentials
from ..openapi_credentials import OpenApiCredentialsError, load as load_openapi
from .api import SyncApiError, publish_prepared
from .content import VIDEO_UNSUPPORTED, prepare_content
from .media import SyncMediaError, upload_image as upload_image_bytes
from .preview import ensure_git_exclude, render_preview, try_open_browser, write_preview_files
from .store import beijing_day, locked_store, new_id, publish_limit, read_store
from .store import _now

REVIEW_TTL_SECONDS = 30 * 60


class SyncServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def save_draft(draft: Mapping[str, object], *, draft_id: str | None = None, expected_revision: int | None = None) -> dict[str, object]:
    """保存草稿。允许先保存尚未通过校验的内容，发布时才会拦下。"""
    _require_draft_shape(draft)
    with locked_store() as payload:
        drafts = _drafts(payload)
        if draft_id is None:
            draft_id = new_id()
            revision = 1
        else:
            current = drafts.get(draft_id)
            if not isinstance(current, dict):
                raise SyncServiceError("not-found", "草稿不存在。")
            _require_revision(current, expected_revision)
            _require_editable(current)
            revision = int(current["revision"]) + 1
        record = {
            "id": draft_id,
            "revision": revision,
            "updated_at": _timestamp(),
            "draft": _public_draft(draft),
        }
        drafts[draft_id] = record
        reviews = payload.get("reviews")
        if isinstance(reviews, dict):
            reviews.pop(draft_id, None)
        return _copy(record)


def list_drafts(offset: int = 0) -> dict[str, object]:
    if offset < 0:
        raise SyncServiceError("bad-request", "分页位置无效。")
    payload = read_store()
    rows = []
    for record in _drafts(payload).values():
        if not isinstance(record, dict):
            continue
        draft = record.get("draft") if isinstance(record.get("draft"), dict) else {}
        rows.append(
            {
                "id": record.get("id"),
                "revision": record.get("revision"),
                "updated_at": record.get("updated_at"),
                "title": draft.get("title") or "",
                "type": draft.get("type"),
                "publish_state": record.get("publish_state"),
                "published": record.get("published"),
            }
        )
    rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    page = rows[offset:offset + 100]
    result: dict[str, object] = {"drafts": page, "total": len(rows)}
    if offset + len(page) < len(rows):
        result["next_offset"] = offset + len(page)
    return result


def get_draft(draft_id: str) -> dict[str, object]:
    payload = read_store()
    record = _drafts(payload).get(draft_id)
    if not isinstance(record, dict):
        raise SyncServiceError("not-found", "草稿不存在。")
    return _copy(record)


def prepare_saved(draft_id: str | None = None, draft: Mapping[str, object] | None = None, *, expected_revision: int | None = None) -> dict[str, object]:
    """校验草稿。通过时签发一次性预览令牌，发布必须带回这枚令牌。"""
    if draft is not None:
        saved = save_draft(draft, draft_id=draft_id, expected_revision=expected_revision)
        draft_id = str(saved["id"])
    if not draft_id:
        raise SyncServiceError("bad-request", "缺少草稿 ID。")
    with locked_store() as payload:
        record = _drafts(payload).get(draft_id)
        if not isinstance(record, dict):
            raise SyncServiceError("not-found", "草稿不存在。")
        _require_editable(record)
        prepared = prepare_content(record["draft"])  # type: ignore[arg-type]
        preview_token = ""
        if prepared["can_publish"]:
            preview_token = secrets.token_urlsafe(24)
            reviews = payload.setdefault("reviews", {})
            if isinstance(reviews, dict):
                reviews[draft_id] = {
                    "token": preview_token,
                    "revision": record["revision"],
                    "expires": _now() + REVIEW_TTL_SECONDS,
                }
        return {"record": _copy(record), "prepared": prepared, "preview_token": preview_token}


def preview_draft(
    draft_id: str,
    *,
    output_dir: Path | None = None,
    open_browser: bool = False,
) -> dict[str, object]:
    result = prepare_saved(draft_id)
    prepared = result["prepared"]
    assert isinstance(prepared, dict)
    html_text = render_preview(prepared)
    directory = output_dir or (credentials.credentials_dir() / "sync-previews" / draft_id)
    warning = ensure_git_exclude(directory) if output_dir is not None else None
    path = write_preview_files(directory, html_text, prepared)
    opened = try_open_browser(path) if open_browser else False
    result["preview_path"] = str(path)
    result["opened"] = opened
    if warning:
        result["warning"] = warning
    return result


async def publish_draft(
    draft_id: str,
    *,
    confirmed: bool,
    preview_token: str,
    output_dir: Path | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, object]:
    """发布。必须同时满足显式确认、未过期的预览令牌和当前修订。"""
    if confirmed is not True:
        raise SyncServiceError("confirmation-required", "发布需要你在看过预览后明确确认。未确认时不会请求知乎。")
    if not preview_token:
        raise SyncServiceError("confirmation-required", "缺少预览令牌。请先校验并预览当前草稿。")
    with locked_store() as payload:
        record = _drafts(payload).get(draft_id)
        if not isinstance(record, dict):
            raise SyncServiceError("not-found", "草稿不存在。")
        _require_editable(record)
        review = payload.get("reviews")
        review_row = review.get(draft_id) if isinstance(review, dict) else None
        if not isinstance(review_row, dict) or review_row.get("token") != preview_token:
            raise SyncServiceError("confirmation-required", "预览令牌无效。请重新预览当前草稿后再确认发布。")
        if review_row.get("revision") != record.get("revision") or float(review_row.get("expires") or 0) < _now():
            raise SyncServiceError("confirmation-required", "预览已过期或草稿已变化。请重新预览后再确认发布。")
        prepared = prepare_content(record["draft"])  # type: ignore[arg-type]
        if not prepared["can_publish"]:
            raise SyncServiceError("validation-failed", "校验未通过，请先修改草稿。")
        try:
            load_openapi()
        except OpenApiCredentialsError as exc:
            raise SyncServiceError("credentials", str(exc)) from exc
        _consume_publish_attempt(payload)
        record["publish_state"] = "publishing"
        record["updated_at"] = _timestamp()
        if isinstance(review, dict):
            review.pop(draft_id, None)
        draft_snapshot = _copy(record)
    try:
        published = await publish_prepared(prepared, client=client)
    except SyncApiError as exc:
        _finish_failure(draft_id, exc)
        raise SyncServiceError(exc.code, str(exc)) from exc
    with locked_store() as payload:
        record = _drafts(payload)[draft_id]
        assert isinstance(record, dict)
        record["publish_state"] = "published"
        record["published"] = {
            "url": published["url"],
            "content_token": published["content_token"],
            "type": published["type"],
        }
        record["updated_at"] = _timestamp()
        saved = _copy(record)
    if output_dir is not None:
        _write_publish_artifacts(output_dir, prepared, published)
    return {"record": saved, "published": published, "draft": draft_snapshot}


async def upload_image(*, file_name: str, content_base64: str, scene: str, client: httpx.AsyncClient | None = None) -> dict[str, object]:
    encoded = content_base64.strip()
    if not encoded or len(encoded) % 4 or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for ch in encoded):
        raise SyncServiceError("bad-request", "content_base64 不是合法的 base64。")
    try:
        content = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise SyncServiceError("bad-request", "content_base64 不是合法的 base64。") from exc
    if not content:
        raise SyncServiceError("bad-request", "图片内容为空。")
    try:
        return await upload_image_bytes(file_name=file_name, content=content, scene=scene, client=client)
    except SyncMediaError as exc:
        if exc.code == "UNSUPPORTED_TYPE" and "视频" in str(exc):
            raise SyncServiceError(exc.code, VIDEO_UNSUPPORTED) from exc
        raise SyncServiceError(exc.code, str(exc)) from exc


def _finish_failure(draft_id: str, exc: SyncApiError) -> None:
    with locked_store() as payload:
        record = _drafts(payload).get(draft_id)
        if not isinstance(record, dict):
            return
        record["updated_at"] = _timestamp()
        if exc.definite:
            record.pop("publish_state", None)
            record["last_error"] = str(exc)
        else:
            record["publish_state"] = "uncertain"
            record["last_error"] = "未能确认发布结果，请到知乎核对，不要重复发布。修改内容请另存为新草稿。"


def _consume_publish_attempt(payload: dict[str, object]) -> None:
    limit = publish_limit()
    attempts = payload.setdefault("publish_attempts", {})
    if not isinstance(attempts, dict):
        raise SyncServiceError("bad-store", "发布计数已损坏，已停止发布。")
    day = beijing_day()
    used = attempts.get(day, 0)
    if not isinstance(used, int) or used < 0:
        raise SyncServiceError("bad-store", "发布计数已损坏，已停止发布。")
    if used >= limit:
        raise SyncServiceError("rate-limited", f"本机今日发布尝试已达 {limit} 次上限。")
    attempts[day] = used + 1


def _write_publish_artifacts(directory: Path, prepared: dict[str, object], published: dict[str, object]) -> None:
    from .content import build_publish_request
    import json
    from datetime import datetime

    ensure_git_exclude(directory)
    target = directory / "publish"
    target.mkdir(parents=True, exist_ok=True)
    request = json.dumps(build_publish_request(prepared), ensure_ascii=False, indent=2)
    response = json.dumps(
        {"status": 0, "msg": "success", "data": {key: published[key] for key in ("type", "content_token", "url")}},
        ensure_ascii=False,
        indent=2,
    )
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    (target / "latest-request.json").write_text(request, encoding="utf-8")
    (target / "latest-response.json").write_text(response, encoding="utf-8")
    (target / f"{stamp}-request.json").write_text(request, encoding="utf-8")
    (target / f"{stamp}-response.json").write_text(response, encoding="utf-8")


def _require_draft_shape(draft: Mapping[str, object]) -> None:
    if len(str(draft.get("title") or "")) > 10_000 or len(str(draft.get("body") or "")) > 200_000:
        raise SyncServiceError("bad-request", "草稿标题或正文过长。")
    content_type = str(draft.get("type") or draft.get("content_type") or "")
    if content_type not in {"article", "question", "pin"}:
        raise SyncServiceError("bad-request", "type 必须是 article、question 或 pin。")
    if not isinstance(draft.get("title", ""), str) or not isinstance(draft.get("body", ""), str):
        raise SyncServiceError("bad-request", "标题和正文必须是字符串。")


def _public_draft(draft: Mapping[str, object]) -> dict[str, object]:
    prepared = prepare_content(draft)
    normalized = prepared.get("draft")
    if isinstance(normalized, dict) and normalized:
        return _copy(normalized)
    return _copy(dict(draft))


def _drafts(payload: dict[str, object]) -> dict[str, object]:
    drafts = payload.setdefault("drafts", {})
    if not isinstance(drafts, dict):
        raise SyncServiceError("bad-store", "草稿文件已损坏。")
    return drafts


def _require_revision(record: dict[str, object], expected: int | None) -> None:
    if expected is None or record.get("revision") != expected:
        raise SyncServiceError("conflict", "草稿已更新，请重新读取后再修改。")


def _require_editable(record: dict[str, object]) -> None:
    if record.get("publish_state"):
        raise SyncServiceError("publish-locked", "这份草稿已经提交过发布。请先核对知乎上的结果；要修改请另存为新草稿。")


def _timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(_now(), timezone.utc).isoformat()


def _copy(value: dict[str, object]) -> dict[str, object]:
    import json

    return json.loads(json.dumps(value, ensure_ascii=False))
