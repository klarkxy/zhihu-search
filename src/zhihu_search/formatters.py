"""格式化层：把知乎 API 返回的原始数据格式化成可读文本。

CLI（默认）、MCP 服务器都共用此层。需要 JSON 输出时，调用方自行
序列化 ``commands.CommandResult``。
"""

from __future__ import annotations

from datetime import datetime, timezone


def format_search_items(data: dict | None, scope: str) -> str:
    """把搜索结果格式化成易读的 Markdown 文本。"""
    items = data.get("Items") if data else None
    if not items:
        empty_reason = (data or {}).get("EmptyReason") or "无结果"
        return f"未找到匹配内容（{empty_reason}）。"

    lines: list[str] = []
    for idx, item in enumerate(items, 1):
        title = item.get("Title") or "(无标题)"
        ctype = item.get("ContentType") or "内容"
        url = item.get("Url") or ""
        summary = (item.get("ContentText") or "").strip()
        votes = item.get("VoteUpCount", 0)
        comments = item.get("CommentCount", 0)
        author = item.get("AuthorName") or "匿名"
        auth_level = item.get("AuthorityLevel") or "?"
        edit_time = item.get("EditTime")
        edit_time_str = (
            format_timestamp(edit_time) if isinstance(edit_time, int) else ""
        )

        lines.append(f"### {idx}. {title}")
        lines.append(f"- 类型：{ctype}　|　作者：{author}　|　权威：{auth_level}")
        lines.append(f"- 链接：{url}")
        if edit_time_str:
            lines.append(f"- 时间：{edit_time_str}")
        lines.append(f"- 数据：赞同 {votes}　|　评论 {comments}")
        if summary:
            lines.append("")
            lines.append(_truncate(summary, 400))
        lines.append("")
    return "\n".join(lines).rstrip()


def format_hot_items(data: dict | None) -> str:
    """热榜 Markdown 格式化。"""
    items = data.get("Items") if data else None
    if not items:
        return "热榜为空。"
    lines: list[str] = ["## 知乎热榜\n"]
    for rank, item in enumerate(items, 1):
        title = item.get("Title") or "(无标题)"
        url = item.get("Url") or ""
        thumb = item.get("ThumbnailUrl") or ""
        summary = item.get("Summary") or ""
        lines.append(f"**{rank}. {title}**")
        if url:
            lines.append(url)
        if thumb:
            lines.append(f"封面：{thumb}")
        if summary:
            lines.append(_truncate(summary, 200))
        lines.append("")
    return "\n".join(lines).rstrip()


def format_zhida_answer(data: dict | None) -> str:
    """直答回答 Markdown 格式化。

    如果回答包含 ``reasoning_content``，先输出思考过程，再输出最终回答。
    """
    if not data:
        return "（直答无返回内容）"
    parts: list[str] = []
    if data.get("reasoning_content"):
        parts.append(f"【思考过程】\n{data['reasoning_content']}")
    parts.append(data.get("content") or "")
    return "\n\n".join(parts).strip()


def format_timestamp(ts: int) -> str:
    """秒级时间戳 → 'YYYY-MM-DD HH:MM'。"""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    except (OverflowError, OSError, ValueError):
        return str(ts)


def _truncate(text: str, limit: int) -> str:
    """截断文本到 limit 字符，超长末尾加 …。"""
    text = text.strip().replace("\r\n", "\n")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


__all__ = [
    "format_search_items",
    "format_hot_items",
    "format_zhida_answer",
    "format_timestamp",
]
