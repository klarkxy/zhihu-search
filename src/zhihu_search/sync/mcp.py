"""可选 MCP 档位里的同步工具。参数里不接收任何密钥。"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import Field

from .service import SyncServiceError, get_draft, list_drafts, prepare_saved, preview_draft, publish_draft, save_draft, upload_image

PUBLISH_ANNOTATIONS = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)
WRITE_ANNOTATIONS = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
UPLOAD_ANNOTATIONS = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
READ_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


def register(mcp: object) -> None:
    tool = getattr(mcp, "tool")

    @tool(
        name="sync_list",
        title="列知乎同步草稿",
        description="列出本机保存的知乎文章、提问和想法草稿。不访问网络，也不返回密钥。",
        annotations=READ_ANNOTATIONS,
    )
    async def sync_list(
        offset: Annotated[int, Field(ge=0, description="分页起点，下一页使用返回的 next_offset。")] = 0,
    ) -> ToolResult:
        return _call("sync_list", lambda: list_drafts(offset))

    @tool(
        name="sync_get",
        title="读取知乎同步草稿",
        description="按 ID 读取一份本地草稿。不返回发布密钥或预览令牌。",
        annotations=READ_ANNOTATIONS,
    )
    async def sync_get(
        draft_id: Annotated[str, Field(min_length=1, description="草稿 ID。")],
    ) -> ToolResult:
        return _call("sync_get", lambda: get_draft(draft_id))

    @tool(
        name="sync_save",
        title="保存知乎同步草稿",
        description=(
            "保存文章、提问或想法草稿。只做格式适配所需的原样保存，不删改正文，也不发布。"
            "图片请先用 sync_upload_image 上传，再把返回的 url 写入正文或 images_json。"
        ),
        annotations=WRITE_ANNOTATIONS,
    )
    async def sync_save(
        content_type: Literal["article", "question", "pin"],
        title: Annotated[str, Field(max_length=10_000)],
        body: Annotated[str, Field(max_length=200_000)],
        body_format: Literal["markdown", "html"] = "markdown",
        draft_id: Annotated[str | None, Field(description="更新已有草稿时填写。")] = None,
        expected_revision: Annotated[int | None, Field(description="更新时填写上次读到的 revision。")] = None,
        images_json: Annotated[str | None, Field(description="已上传图片的 JSON 数组。")] = None,
        link_card_json: Annotated[str | None, Field(description="想法链接卡片 JSON。与图片互斥。")] = None,
        comment_permission: str | None = None,
        creation_statement: str | None = None,
        table_of_contents_enabled: bool | None = None,
        topics: list[str] | None = None,
        ring: str | None = None,
    ) -> ToolResult:
        try:
            draft = _draft_from_args(
                content_type, title, body, body_format, images_json, link_card_json,
                comment_permission, creation_statement, table_of_contents_enabled, topics, ring,
            )
        except SyncServiceError as exc:
            return _envelope("sync_save", False, error=str(exc))
        return _call("sync_save", lambda: save_draft(draft, draft_id=draft_id, expected_revision=expected_revision))

    @tool(
        name="sync_prepare",
        title="校验知乎同步草稿",
        description=(
            "把草稿适配成知乎 HTML 并校验。通过时返回 preview_token。"
            "这不是发布。发布前必须把预览给用户看，并得到用户明确确认。"
        ),
        annotations=WRITE_ANNOTATIONS,
    )
    async def sync_prepare(
        draft_id: Annotated[str, Field(min_length=1, description="已保存的草稿 ID。")],
    ) -> ToolResult:
        return _call("sync_prepare", lambda: prepare_saved(draft_id))

    @tool(
        name="sync_preview",
        title="预览知乎同步草稿",
        description=(
            "生成本地预览 HTML。把路径和摘要交给用户，等用户明确确认后再发布。"
            "不要把生成预览当成用户已经同意发布。"
        ),
        annotations=WRITE_ANNOTATIONS,
    )
    async def sync_preview(
        draft_id: Annotated[str, Field(min_length=1)],
    ) -> ToolResult:
        return _call("sync_preview", lambda: preview_draft(draft_id))

    @tool(
        name="sync_publish",
        title="确认后发布到知乎",
        description=(
            "把已预览的文章、提问或想法发布到知乎。这是公开的、不可自动撤销的操作。"
            "只有用户在当前对话里明确确认最新预览后，才可以把 confirmed 设为 true 并传入该次 preview_token。"
            "不要自行确认。不接收 App Key、App Secret 或 Access Secret。"
        ),
        annotations=PUBLISH_ANNOTATIONS,
    )
    async def sync_publish(
        draft_id: Annotated[str, Field(min_length=1)],
        preview_token: Annotated[str, Field(min_length=1, description="sync_prepare 或 sync_preview 返回的令牌。")],
        confirmed: Annotated[bool, Field(description="仅当用户已明确确认这份预览时为 true。")] = False,
    ) -> ToolResult:
        async def run() -> dict[str, object]:
            return await publish_draft(draft_id, confirmed=confirmed, preview_token=preview_token)

        return await _call_async("sync_publish", run)

    @tool(
        name="sync_upload_image",
        title="上传知乎同步图片",
        description=(
            "把 JPEG、PNG、GIF、WebP 或 BMP 上传到知乎。不接收本地路径和密钥。"
            "视频不支持。上传成功后把返回的 url 写入草稿，而不是把本地路径写进正文。"
        ),
        annotations=UPLOAD_ANNOTATIONS,
    )
    async def sync_upload_image(
        file_name: Annotated[str, Field(min_length=1, max_length=200)],
        content_base64: Annotated[str, Field(min_length=4, description="图片的标准 base64。")],
        scene: Literal["article", "question", "pin"],
    ) -> ToolResult:
        async def run() -> dict[str, object]:
            return await upload_image(file_name=file_name, content_base64=content_base64, scene=scene)

        return await _call_async("sync_upload_image", run)


def _draft_from_args(
    content_type: str,
    title: str,
    body: str,
    body_format: str,
    images_json: str | None,
    link_card_json: str | None,
    comment_permission: str | None,
    creation_statement: str | None,
    table_of_contents_enabled: bool | None,
    topics: list[str] | None,
    ring: str | None,
) -> dict[str, object]:
    draft: dict[str, object] = {
        "type": content_type,
        "title": title,
        "body": body,
        "format": body_format,
    }
    if images_json:
        parsed = _json_object("images_json", images_json, expect="list")
        draft["images"] = parsed
    if link_card_json:
        draft["link_card"] = _json_object("link_card_json", link_card_json, expect="dict")
    settings: dict[str, object] = {}
    if comment_permission:
        settings["comment_permission"] = comment_permission
    if creation_statement:
        settings["creation_statement"] = creation_statement
    if table_of_contents_enabled is not None:
        settings["table_of_contents_enabled"] = table_of_contents_enabled
    if topics:
        settings["topics"] = topics
    if ring:
        settings["ring"] = ring
    if settings:
        draft["settings"] = settings
    return draft


def _json_object(name: str, raw: str, *, expect: str) -> object:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SyncServiceError("bad-request", f"{name} 不是合法 JSON。") from exc
    if expect == "list" and not isinstance(value, list):
        raise SyncServiceError("bad-request", f"{name} 必须是 JSON 数组。")
    if expect == "dict" and not isinstance(value, dict):
        raise SyncServiceError("bad-request", f"{name} 必须是 JSON 对象。")
    return value


def _call(kind: str, func: object) -> ToolResult:
    try:
        data = func()  # type: ignore[operator]
    except (SyncServiceError, RuntimeError) as exc:
        return _envelope(kind, False, error=str(exc))
    return _envelope(kind, True, data=data)


async def _call_async(kind: str, func: object) -> ToolResult:
    try:
        data = await func()  # type: ignore[operator]
    except (SyncServiceError, RuntimeError) as exc:
        return _envelope(kind, False, error=str(exc))
    return _envelope(kind, True, data=data)


def _envelope(kind: str, success: bool, *, data: object | None = None, error: str | None = None) -> ToolResult:
    payload: dict[str, object] = {"success": success, "kind": kind}
    if success:
        payload["data"] = data
    else:
        payload["error"] = error
    return ToolResult(content=json.dumps(payload, ensure_ascii=False, indent=2), is_error=not success)
