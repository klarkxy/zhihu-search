"""格式化层：把知乎 API 返回的原始数据格式化成可读文本。

CLI（默认）、MCP 服务器都共用此层。需要 JSON 输出时，调用方自行
序列化 ``commands.CommandResult``。
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any


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


def format_quota(data: Any) -> str:
    """格式化知乎开放平台返回的官方自然日额度。"""
    items = data
    if isinstance(data, dict):
        items = _pick(data, "Data", "data", "Items", "items")
    if not isinstance(items, list) or not items:
        return "官方额度列表为空。"

    lines: list[str] = ["## 官方每日额度", ""]
    for raw_item in items:
        item = raw_item if isinstance(raw_item, dict) else {}
        api_id = _pick(item, "APIID", "api_id") or "unknown"
        name = _pick(item, "APIName", "api_name") or api_id
        total = _pick(item, "TotalQuota", "total_quota")
        used = _pick(item, "TotalUsed", "total_used")
        remaining = _pick(item, "RemainingQuota", "remaining_quota")
        lines.append(f"- {name} (`{api_id}`)：已用 {used} / {total}，剩余 {remaining}")

    lines.extend(
        [
            "",
            "知识库的列表、内容、上传和检索共用 `knowledge` 额度；"
            "PDF 解析与 PPT 生成共用 `tools` 额度；"
            "问题回答摘要使用 `question_answers` 额度；"
            "问题推荐、本人全文、评论和创作统计共用 `creator` 额度。",
        ]
    )
    return "\n".join(lines)


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


def format_content_items(
    data: dict | None,
    heading: str = "知乎内容",
) -> str:
    """格式化用户创作、近期收藏或指定收藏夹中的内容。

    新接口目前使用 PascalCase 字段。这里同时兼容常见的小写和
    snake_case 写法，并忽略后续新增字段，避免上游做兼容扩展时 CLI
    因单个未知字段失效。
    """
    payload = _payload(data)
    items = _item_list(payload)
    if not items:
        return f"{heading}为空。"

    lines: list[str] = [f"## {heading}", ""]
    for idx, raw_item in enumerate(items, 1):
        item = raw_item if isinstance(raw_item, dict) else {}
        title = _pick(item, "Title", "title") or "(无标题)"
        content_type = (
            _pick(item, "ContentType", "content_type", "Type", "type") or "内容"
        )
        url = _pick(item, "Url", "url") or ""
        summary = _pick(item, "Summary", "summary", "ContentText", "content_text")
        created_at = _pick(item, "CreatedAt", "created_at")
        fav_time = _pick(item, "FavTime", "fav_time")
        likes = _pick(item, "LikeCount", "like_count", "VoteUpCount")
        comments = _pick(item, "CommentCount", "comment_count")
        favorites = _pick(item, "FavoriteCount", "favorite_count")
        author = _pick(item, "Author", "author")

        lines.append(f"### {idx}. {title}")
        lines.append(f"- 类型：{content_type}")
        if url:
            lines.append(f"- 链接：{url}")
        author_text = _format_author(author)
        if author_text:
            lines.append(f"- 作者：{author_text}")

        times: list[str] = []
        created_text = _format_time(created_at)
        fav_text = _format_time(fav_time)
        if created_text:
            times.append(f"创建 {created_text}")
        if fav_text:
            times.append(f"收藏 {fav_text}")
        if times:
            lines.append("- 时间：" + "　|　".join(times))

        metrics: list[str] = []
        if likes is not None:
            metrics.append(f"赞同 {likes}")
        if comments is not None:
            metrics.append(f"评论 {comments}")
        if favorites is not None:
            metrics.append(f"收藏 {favorites}")
        if metrics:
            lines.append("- 数据：" + "　|　".join(metrics))

        favlists = _pick(item, "Favlists", "favlists")
        if isinstance(favlists, list):
            rendered_favlists = [
                _format_favlist_reference(entry)
                for entry in favlists
                if isinstance(entry, dict)
            ]
            rendered_favlists = [entry for entry in rendered_favlists if entry]
            if rendered_favlists:
                lines.append("- 所在收藏夹：" + "；".join(rendered_favlists))

        if isinstance(summary, str) and summary.strip():
            lines.append("")
            lines.append(_truncate(summary, 400))
        lines.append("")

    paging = _format_paging(payload)
    if paging:
        lines.append(paging)
    return "\n".join(lines).rstrip()


def format_followees(data: dict | None) -> str:
    """格式化用户关注列表。"""
    payload = _payload(data)
    items = _item_list(payload)
    if not items:
        return "关注列表为空。"

    lines: list[str] = ["## 关注列表", ""]
    for idx, raw_item in enumerate(items, 1):
        item = raw_item if isinstance(raw_item, dict) else {}
        name = _pick(item, "Fullname", "fullname", "Name", "name") or "知乎用户"
        url = _pick(item, "Url", "url") or ""
        url_token = _pick(item, "UrlToken", "url_token")
        headline = _pick(item, "Headline", "headline")
        avatar = _pick(item, "AvatarUrl", "avatar_url")
        gender = _pick(item, "Gender", "gender")
        followers = _pick(item, "FollowerCount", "follower_count")

        lines.append(f"### {idx}. {name}")
        if url:
            lines.append(f"- 主页：{url}")
        if url_token not in (None, ""):
            lines.append(f"- URL Token：{url_token}")
        details: list[str] = []
        if followers is not None:
            details.append(f"粉丝 {followers}")
        if gender is not None:
            details.append(f"性别标识 {gender}")
        if details:
            lines.append("- 数据：" + "　|　".join(details))
        if isinstance(headline, str) and headline.strip():
            lines.append(f"- 简介：{_truncate(headline, 200)}")
        if avatar:
            lines.append(f"- 头像：{avatar}")
        lines.append("")

    paging = _format_paging(payload)
    if paging:
        lines.append(paging)
    return "\n".join(lines).rstrip()


def format_favlists(data: dict | None) -> str:
    """格式化用户收藏夹列表。"""
    payload = _payload(data)
    items = _item_list(payload)
    if not items:
        return "收藏夹列表为空。"

    lines: list[str] = ["## 收藏夹列表", ""]
    for idx, raw_item in enumerate(items, 1):
        item = raw_item if isinstance(raw_item, dict) else {}
        title = _pick(item, "Title", "title") or "(未命名收藏夹)"
        url = _pick(item, "Url", "url") or ""
        url_token = _pick(item, "UrlToken", "url_token")
        description = _pick(item, "Description", "description")
        is_public = _pick(item, "IsPublic", "is_public")

        lines.append(f"### {idx}. {title}")
        if isinstance(is_public, bool):
            lines.append(f"- 可见性：{'公开' if is_public else '私密'}")
        elif is_public is not None:
            lines.append(f"- 可见性：{is_public}")
        if url:
            lines.append(f"- 链接：{url}")
        if url_token not in (None, ""):
            lines.append(f"- URL Token：{url_token}")
        if isinstance(description, str) and description.strip():
            lines.append(f"- 描述：{_truncate(description, 300)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_knowledge_bases(data: dict | None) -> str:
    """格式化知识库列表。"""
    payload = _payload(data)
    items = _item_list(payload)
    if not items:
        return "知识库列表为空。首次使用请先登录直答知识库完成初始化：https://zhida.zhihu.com/repositories/square"

    lines: list[str] = ["## 知识库列表", ""]
    for idx, raw_item in enumerate(items, 1):
        item = raw_item if isinstance(raw_item, dict) else {}
        name = _pick(item, "Name", "name") or "(未命名知识库)"
        knowledge_base_id = _pick(
            item, "KnowledgeBaseID", "knowledge_base_id", "KnowledgeBaseId"
        )
        description = _pick(item, "Description", "description")
        relation = _pick(item, "Relation", "relation")
        visibility = _pick(item, "Visibility", "visibility")
        is_default = _pick(item, "IsDefault", "is_default")
        content_count = _pick(item, "ContentCount", "content_count")
        updated_at = _pick(item, "UpdatedAt", "updated_at")

        lines.append(f"### {idx}. {name}")
        if knowledge_base_id not in (None, ""):
            lines.append(f"- 知识库 ID：{knowledge_base_id}")
        details: list[str] = []
        if relation not in (None, ""):
            details.append(f"关系 {relation}")
        if visibility not in (None, ""):
            details.append(f"可见性 {visibility}")
        if isinstance(is_default, bool):
            details.append("默认知识库" if is_default else "非默认")
        if content_count is not None:
            details.append(f"内容 {content_count}")
        if details:
            lines.append("- 属性：" + "　|　".join(details))
        updated_text = _format_time(updated_at)
        if updated_text:
            lines.append(f"- 更新：{updated_text}")
        if isinstance(description, str) and description.strip():
            lines.append(f"- 描述：{_truncate(description, 300)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_knowledge_items(data: dict | None) -> str:
    """格式化知识库内容列表。"""
    payload = _payload(data)
    items = _item_list(payload)
    if not items:
        return "知识库内容为空。"

    lines: list[str] = ["## 知识库内容", ""]
    for idx, raw_item in enumerate(items, 1):
        item = raw_item if isinstance(raw_item, dict) else {}
        title = _pick(item, "Title", "title") or "(无标题)"
        content_type = _pick(item, "ContentType", "content_type") or "内容"
        abstract = _pick(item, "Abstract", "abstract")
        origin_url = _pick(item, "OriginUrl", "origin_url")
        recall_id = _pick(
            item, "RecallContentID", "recall_content_id", "RecallContentId"
        )
        created_at = _pick(item, "CreatedAt", "created_at")
        updated_at = _pick(item, "UpdatedAt", "updated_at")

        lines.append(f"### {idx}. {title}")
        lines.append(f"- 类型：{content_type}")
        if origin_url:
            lines.append(f"- 来源：{origin_url}")
        if recall_id not in (None, ""):
            lines.append(f"- 内容 ID：{recall_id}")
        times: list[str] = []
        created_text = _format_time(created_at)
        updated_text = _format_time(updated_at)
        if created_text:
            times.append(f"创建 {created_text}")
        if updated_text:
            times.append(f"更新 {updated_text}")
        if times:
            lines.append("- 时间：" + "　|　".join(times))
        if isinstance(abstract, str) and abstract.strip():
            lines.append("")
            lines.append(_truncate(abstract, 400))
        lines.append("")

    paging = _format_cursor_paging(payload)
    if paging:
        lines.append(paging)
    return "\n".join(lines).rstrip()


def format_knowledge_upload(data: dict | None) -> str:
    """格式化知识库文件上传结果。"""
    payload = _payload(data)
    if not payload:
        return "（知识库上传无返回内容）"

    knowledge_base_id = _pick(
        payload, "KnowledgeBaseID", "knowledge_base_id", "KnowledgeBaseId"
    )
    recall_id = _pick(
        payload, "RecallContentID", "recall_content_id", "RecallContentId"
    )
    file_name = _pick(payload, "FileName", "file_name")
    file_size = _pick(payload, "FileSize", "file_size")
    title = _pick(payload, "Title", "title")
    abstract = _pick(payload, "Abstract", "abstract")
    origin_url = _pick(payload, "OriginUrl", "origin_url")

    lines: list[str] = ["## 知识库上传成功"]
    if knowledge_base_id not in (None, ""):
        lines.append(f"- 知识库 ID：{knowledge_base_id}")
    if recall_id not in (None, ""):
        lines.append(f"- 内容 ID：{recall_id}")
    if file_name not in (None, ""):
        lines.append(f"- 文件名：{file_name}")
    if file_size is not None:
        lines.append(f"- 大小：{file_size} 字节")
    if title not in (None, ""):
        lines.append(f"- 标题：{title}")
    if origin_url:
        lines.append(f"- 源文件：{origin_url}")
    if isinstance(abstract, str) and abstract.strip():
        lines.append(f"- 摘要：{_truncate(abstract, 400)}")
    if len(lines) == 1:
        lines.append("- 状态：上游未返回可识别的上传字段")
    return "\n".join(lines)


def format_knowledge_search(data: dict | None) -> str:
    """格式化知识库检索结果。"""
    payload = _payload(data)
    items = _item_list(payload)
    if not items:
        return "知识库检索无匹配结果。"

    lines: list[str] = ["## 知识库检索结果", ""]
    for idx, raw_item in enumerate(items, 1):
        item = raw_item if isinstance(raw_item, dict) else {}
        doc_name = _pick(item, "DocName", "doc_name") or "(未命名文档)"
        knowledge_base_id = _pick(
            item, "KnowledgeBaseID", "knowledge_base_id", "KnowledgeBaseId"
        )
        recall_id = _pick(
            item, "RecallContentID", "recall_content_id", "RecallContentId"
        )
        origin_url = _pick(item, "OriginUrl", "origin_url")
        content = _pick(item, "Content", "content")

        lines.append(f"### {idx}. {doc_name}")
        if knowledge_base_id not in (None, ""):
            lines.append(f"- 知识库 ID：{knowledge_base_id}")
        if recall_id not in (None, ""):
            lines.append(f"- 内容 ID：{recall_id}")
        if origin_url:
            lines.append(f"- 来源：{origin_url}")
        snippets = content if isinstance(content, list) else []
        rendered = [
            _truncate(str(snippet).strip(), 400)
            for snippet in snippets
            if str(snippet).strip()
        ]
        if rendered:
            lines.append("")
            lines.extend(f"- {snippet}" for snippet in rendered)
        lines.append("")
    return "\n".join(lines).rstrip()


def format_upload_result(data: dict | None) -> str:
    """格式化 PDF 文件上传结果。"""
    payload = _payload(data)
    if not payload:
        return "（PDF 上传无返回内容）"
    file_id = _pick(payload, "file_id", "FileId", "fileId")
    if file_id in (None, ""):
        return "PDF 上传完成，但响应中没有 file_id。"
    return (
        "PDF 上传成功。\n"
        f"- file_id：{file_id}\n"
        "- 提示：上传文件需在 24 小时内用于创建解析任务。"
    )


def format_task_status(data: dict | None, task_type: str) -> str:
    """格式化 PDF 解析或 PPT 生成任务的创建/查询结果。"""
    label = _task_label(task_type)
    payload = _payload(data)
    if not payload:
        return f"（{label} 任务无返回内容）"

    task_id = _pick(payload, "task_id", "TaskId", "taskId")
    status = _pick(payload, "task_status", "TaskStatus", "taskStatus", "status")
    progress = _pick(payload, "progress", "Progress")
    result = _pick(payload, "result", "Result")
    error = _pick(payload, "error", "Error")

    lines: list[str] = [f"## {label} 任务"]
    if task_id not in (None, ""):
        lines.append(f"- 任务 ID：{task_id}")
    if status not in (None, ""):
        status_text = str(status)
        translated = {
            "pending": "等待处理",
            "running": "处理中",
            "succeeded": "已成功",
            "failed": "失败",
        }.get(status_text.lower())
        if translated:
            status_text += f"（{translated}）"
        lines.append(f"- 状态：{status_text}")

    progress_text = _format_progress(progress)
    if progress_text:
        lines.append(f"- 进度：{progress_text}")

    if isinstance(result, dict):
        result_url = _pick(result, "url", "Url")
        summary = _pick(result, "summary", "Summary")
        expires_at = _pick(result, "expires_at_ms", "ExpiresAtMs", "expiresAtMs")
        if result_url:
            lines.append(f"- 结果链接：{result_url}")
        if isinstance(summary, str) and summary.strip():
            lines.append(f"- 摘要：{_truncate(summary, 400)}")
        expires_text = _format_millisecond_time(expires_at)
        if expires_text:
            lines.append(f"- 链接过期时间：{expires_text}")
    elif result not in (None, ""):
        lines.append(f"- 结果：{result}")

    if isinstance(error, dict):
        error_code = _pick(error, "code", "Code")
        error_message = _pick(error, "message", "Message")
        error_parts = [
            str(part)
            for part in (error_code, error_message)
            if part not in (None, "")
        ]
        if error_parts:
            lines.append("- 错误：" + " — ".join(error_parts))
    elif error not in (None, ""):
        lines.append(f"- 错误：{error}")

    if len(lines) == 1:
        lines.append("- 状态：上游未返回可识别的任务字段")
    return "\n".join(lines)


def format_question_recommendations(data: dict | None) -> str:
    """格式化适合回答的问题推荐。没有分页。"""
    payload = _payload(data)
    items = _item_list(payload)
    if not items:
        return "没有推荐问题。返回条目可以少于请求数量，也不支持翻页。"

    lines: list[str] = [
        "## 适合回答的问题",
        "",
        "未提供主题时按当前账号画像推荐；条目可以少于请求数量，不支持翻页。",
        "",
    ]
    for idx, raw_item in enumerate(items, 1):
        item = raw_item if isinstance(raw_item, dict) else {}
        title = _pick(item, "Title", "title") or "(无标题)"
        url = _pick(item, "Url", "url") or ""
        lines.append(f"{idx}. {title}")
        if url:
            lines.append(url)
        lines.append("")
    return "\n".join(lines).rstrip()


def format_question_answers(data: dict | None) -> str:
    """格式化问题下的回答摘要。摘要不是全文，也不要按条数自行翻页。"""
    payload = _payload(data)
    items = _item_list(payload)
    lines: list[str] = [
        "## 问题回答摘要",
        "",
        "Summary 是上游返回的摘要或截取文本，不是回答全文，也不是额外生成的 AI 摘要。",
        "单页条数可能少于 Limit；只使用 Paging，不要按过滤后的条数计算下一页。",
        "",
    ]
    if not items:
        lines.append("本页没有可展示的回答摘要。")
    for idx, raw_item in enumerate(items, 1):
        item = raw_item if isinstance(raw_item, dict) else {}
        token = _pick(item, "ContentToken", "content_token") or ""
        url = _pick(item, "Url", "url") or ""
        summary = _pick(item, "Summary", "summary")
        lines.append(f"### {idx}. 回答 {token or '(无 Token)'}")
        if url:
            lines.append(f"- 链接：{url}")
        if isinstance(summary, str) and summary.strip():
            lines.append("")
            lines.append(_truncate(_plain_untrusted(summary), 400))
        lines.append("")
    paging = _format_paging(payload, strict_next_offset=True)
    if paging:
        lines.append(paging)
    totals = _paging_value(payload, "Totals", "totals", "Total", "total")
    if totals is not None:
        lines.append("Totals 可能包含被过滤的回答，不等于最终可读摘要数。")
    return "\n".join(lines).rstrip()


def format_content_detail(data: dict | None) -> str:
    """格式化本人创作全文。正文按不可信 HTML 清洗后再展示。"""
    payload = _payload(data)
    if not payload:
        return "创作全文为空。空正文不能视为全文。"

    title = _pick(payload, "Title", "title")
    content_type = _pick(payload, "ContentType", "content_type") or "内容"
    token = _pick(payload, "ContentToken", "content_token")
    url = _pick(payload, "Url", "url") or ""
    lines: list[str] = [
        "## 创作全文",
        "",
        "仅当前 Access Secret 所属账号的已发布内容。视频只返回关联正文，不提供视频文件。",
        "",
        f"- 类型：{content_type}",
    ]
    if title not in (None, ""):
        lines.append(f"- 标题：{title}")
    if token not in (None, ""):
        lines.append(f"- Token：{token}")
    if url:
        lines.append(f"- 链接：{url}")

    if "Body" not in payload and "body" not in payload:
        lines.append("- 正文：未返回，不能视为全文")
        return "\n".join(lines)

    body = _pick(payload, "Body", "body")
    plain = _plain_untrusted(body) if isinstance(body, str) else ""
    if not plain:
        lines.append("- 正文：为空，不能视为全文")
        return "\n".join(lines)
    lines.extend(["", plain])
    return "\n".join(lines).rstrip()


def format_content_comments(data: dict | None) -> str:
    """格式化本人创作下的评论。子评论不保证完整。"""
    payload = _payload(data)
    items = _item_list(payload)
    lines: list[str] = [
        "## 创作评论",
        "",
        "评论文本按不可信内容展示。Children 只是上游附带的子评论，不保证完整。",
        "不要因为本页条数较少或为空就停止翻页。",
        "",
    ]
    if not items:
        lines.append("本页没有根评论。")
    for idx, raw_item in enumerate(items, 1):
        item = raw_item if isinstance(raw_item, dict) else {}
        comment = item.get("Comment")
        if not isinstance(comment, dict):
            comment = item
        lines.extend(_format_comment(comment, label=f"{idx}"))
        children = item.get("Children")
        if isinstance(children, list) and children:
            lines.append("- 附带子评论（不保证完整）：")
            for child in children:
                if isinstance(child, dict):
                    lines.extend(_format_comment(child, label="子评论", indent="  "))
        lines.append("")
    paging = _format_paging(payload, strict_next_offset=True)
    if paging:
        lines.append(paging)
    return "\n".join(lines).rstrip()


def format_creator_account_stats(data: dict | None) -> str:
    """格式化账号创作统计。缺失指标不补零，比例保持上游原值。"""
    payload = _payload(data)
    if not payload:
        return "账号创作数据为空。未返回的指标不补零。"
    lines = [
        "## 账号创作数据",
        "",
        "未返回的指标保持省略，不补零。比例沿用上游原值，不换算成百分比。",
        "省略日期时使用上游默认统计范围，这里不猜测具体天数。",
        "",
    ]
    lines.extend(_format_stats_value(payload))
    return "\n".join(lines).rstrip()


def format_creator_content_stats(data: dict | None) -> str:
    """格式化单篇创作统计。空列表不等于各项指标为零。"""
    payload = _payload(data)
    items = _item_list(payload)
    lines = [
        "## 单篇创作数据",
        "",
        "未返回的指标保持省略，不补零。比例沿用上游原值，不换算成百分比。",
        "",
    ]
    if not items:
        lines.append("没有单篇统计。空列表不等于各项指标为零。")
        return "\n".join(lines).rstrip()
    for idx, raw_item in enumerate(items, 1):
        item = raw_item if isinstance(raw_item, dict) else {}
        title = _pick(item, "Title", "title") or "(无标题)"
        lines.append(f"### {idx}. {title}")
        rest = {
            key: value
            for key, value in item.items()
            if key not in {"Title", "title"}
        }
        lines.extend(_format_stats_value(rest, indent=""))
        lines.append("")
    return "\n".join(lines).rstrip()


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


def _payload(data: dict | None) -> dict[str, Any]:
    """接受业务 Data 或完整 ``{Data: ...}`` 信封。"""
    if not isinstance(data, dict):
        return {}
    nested = _pick(data, "Data", "data")
    if isinstance(nested, dict):
        return nested
    return data


def _item_list(data: dict[str, Any]) -> list[Any]:
    items = _pick(data, "Items", "items")
    return items if isinstance(items, list) else []


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _format_time(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return format_timestamp(value)
    if value in (None, ""):
        return ""
    return str(value)


def _format_millisecond_time(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(
                value / 1000,
                tz=timezone.utc,
            ).strftime("%Y-%m-%d %H:%M UTC")
        except (OverflowError, OSError, ValueError):
            return str(value)
    if value in (None, ""):
        return ""
    return str(value)


def _format_progress(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        percentage = value * 100 if 0 <= value <= 1 else value
        if float(percentage).is_integer():
            return f"{int(percentage)}%"
        return f"{percentage:.1f}%"
    if value in (None, ""):
        return ""
    return str(value)


def _format_paging(
    data: dict[str, Any],
    *,
    strict_next_offset: bool = False,
) -> str:
    paging = _pick(data, "Paging", "paging")
    if not isinstance(paging, dict):
        return ""
    total = _pick(paging, "Totals", "totals", "Total", "total")
    is_end = _pick(paging, "IsEnd", "is_end")
    next_offset = _pick(paging, "NextOffset", "next_offset")

    parts: list[str] = []
    if total is not None:
        parts.append(f"共 {total} 条")
    if is_end is True:
        parts.append("已到最后一页")
    elif (
        strict_next_offset
        and is_end is False
        and next_offset in (None, "")
    ):
        parts.append("分页信息不完整：IsEnd 为 false 但缺少 NextOffset，请停止翻页")
    elif next_offset not in (None, ""):
        parts.append(f"下一页 Offset：{next_offset}")
    return "分页：" + "；".join(parts) if parts else ""


def _paging_value(data: dict[str, Any], *keys: str) -> Any:
    paging = _pick(data, "Paging", "paging")
    if not isinstance(paging, dict):
        return None
    return _pick(paging, *keys)


_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_END_RE = re.compile(
    r"</(p|div|li|h[1-6]|tr|blockquote)>",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _plain_untrusted(value: str) -> str:
    """把上游 HTML 收成纯文本。展示层不执行也不保留标签。"""
    text = _SCRIPT_STYLE_RE.sub("", value)
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_END_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _format_comment(comment: dict[str, Any], *, label: str, indent: str = "") -> list[str]:
    comment_id = _pick(comment, "ID", "id")
    author = _pick(comment, "AuthorToken", "author_token") or ""
    created_at = _format_time(_pick(comment, "CreatedAt", "created_at"))
    content = _pick(comment, "Content", "content")
    likes = _pick(comment, "LikeCount", "like_count")
    dislikes = _pick(comment, "DislikeCount", "dislike_count")
    header = f"{indent}- {label}"
    if comment_id not in (None, ""):
        header += f" #{comment_id}"
    lines = [header]
    meta: list[str] = []
    if author:
        meta.append(f"作者 {author}")
    if created_at:
        meta.append(created_at)
    if likes is not None:
        meta.append(f"赞 {likes}")
    if dislikes is not None:
        meta.append(f"踩 {dislikes}")
    if meta:
        lines.append(f"{indent}  " + "　|　".join(meta))
    if isinstance(content, str) and content.strip():
        lines.append(f"{indent}  {_plain_untrusted(content)}")
    return lines


_STATS_LABELS = {
    "ContentType": "内容类型",
    "ContentToken": "内容标识",
    "Url": "链接",
    "Title": "标题",
    "Metrics": "内容指标",
    "Audience": "受众画像",
    "CreationCounts": "创作数量",
    "Followers": "粉丝概览",
    "FollowerDetails": "粉丝明细",
    "FollowerProfile": "粉丝画像",
    "Updated": "更新时间",
    "Date": "日期",
    "ViewCount": "阅读",
    "PlayCount": "播放",
    "UpvoteCount": "赞同",
    "CommentCount": "评论",
    "LikeCount": "喜欢",
    "CollectCount": "收藏",
    "ShareCount": "分享",
    "RepinCount": "转发",
    "PublishCount": "发布数",
    "ClickRate": "点击率",
    "ReadFinishedRate": "阅读完成率",
    "PlayFinishedRate": "播放完成率",
    "IncreasedUpvoteCount": "新增赞同",
    "DecreasedUpvoteCount": "减少赞同",
    "IncreasedLikeCount": "新增喜欢",
    "DecreasedLikeCount": "减少喜欢",
    "PageShowUV": "曝光用户数",
    "NewFollowerCount": "新增关注用户",
    "FollowerConversionRate": "转粉率",
    "PositiveInteractionRate": "正向互动率",
    "FollowerGain": "转粉数量",
    "UpvoteCount7Days": "7 日赞同",
    "Yesterday": "昨日",
    "Today": "今日",
    "Status": "状态",
    "Reason": "原因",
    "Source": "访问来源",
    "Activeness": "活跃程度",
    "ActiveTime": "活跃时间",
    "Content": "关联内容",
    "Gender": "性别",
    "Age": "年龄",
    "Interest": "兴趣",
    "Location": "地域",
    "OS": "操作系统",
    "Name": "名称",
    "Ratio": "占比",
    "Count": "数量",
    "FollowCount": "关注数",
    "Answer": "回答",
    "Article": "文章",
    "Video": "视频",
    "Follower": "粉丝",
    "Total": "粉丝总数",
    "NewYesterday": "昨日新增粉丝",
    "CancelledYesterday": "昨日取消关注",
    "ActiveCount": "活跃粉丝",
    "ActiveRatio": "活跃粉丝占比",
    "Daily": "日序列",
    "Period": "周期",
    "Interactions": "互动",
    "Creators": "互动创作者",
    "Avatar": "头像",
    "MemberToken": "用户标识",
    "NetIncrease": "净增粉丝",
    "NewCount": "新增粉丝",
    "UnfollowCount": "取消关注",
    "HomepageVisitorCount": "主页访客",
    "HomepageFollowCount": "主页转粉",
    "HomepageConversionRate": "主页转粉率",
}


def _format_stats_value(value: Any, *, indent: str = "") -> list[str]:
    """只打印上游实际返回的字段。"""
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            label = _STATS_LABELS.get(str(key), str(key))
            if isinstance(item, (dict, list)):
                lines.append(f"{indent}- {label}：")
                lines.extend(_format_stats_value(item, indent=indent + "  "))
            else:
                lines.append(f"{indent}- {label}：{item}")
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{indent}- （空）"]
        lines = []
        for entry in value:
            if isinstance(entry, (dict, list)):
                lines.append(f"{indent}-")
                lines.extend(_format_stats_value(entry, indent=indent + "  "))
            else:
                lines.append(f"{indent}- {entry}")
        return lines
    return [f"{indent}{value}"]


def _format_author(author: Any) -> str:
    if not isinstance(author, dict):
        return ""
    name = _pick(author, "Name", "name") or "知乎用户"
    url = _pick(author, "Url", "url")
    headline = _pick(author, "Headline", "headline")
    parts = [str(name)]
    if url:
        parts.append(str(url))
    if isinstance(headline, str) and headline.strip():
        parts.append(_truncate(headline, 80))
    return "　|　".join(parts)


def _format_cursor_paging(data: dict[str, Any]) -> str:
    total = _pick(data, "Total", "total", "Totals", "totals")
    has_more = _pick(data, "HasMore", "has_more")
    next_cursor = _pick(data, "NextCursor", "next_cursor")

    parts: list[str] = []
    if total is not None:
        parts.append(f"共 {total} 条")
    if has_more is True and next_cursor not in (None, ""):
        parts.append(f"下一页 Cursor：{next_cursor}")
    elif has_more is False:
        parts.append("已到最后一页")
    elif next_cursor not in (None, ""):
        parts.append(f"下一页 Cursor：{next_cursor}")
    return "分页：" + "；".join(parts) if parts else ""


def _format_favlist_reference(item: dict[str, Any]) -> str:
    title = _pick(item, "Title", "title") or "(未命名收藏夹)"
    url = _pick(item, "Url", "url")
    return f"{title}（{url}）" if url else str(title)


def _task_label(task_type: str) -> str:
    raw_label = str(task_type or "").strip()
    normalized = raw_label.lower()
    if normalized == "pdf":
        return "PDF"
    if normalized == "ppt":
        return "PPT"
    return raw_label or "异步"


__all__ = [
    "format_search_items",
    "format_hot_items",
    "format_quota",
    "format_zhida_answer",
    "format_content_items",
    "format_question_recommendations",
    "format_question_answers",
    "format_content_detail",
    "format_content_comments",
    "format_creator_account_stats",
    "format_creator_content_stats",
    "format_followees",
    "format_favlists",
    "format_knowledge_bases",
    "format_knowledge_items",
    "format_knowledge_upload",
    "format_knowledge_search",
    "format_upload_result",
    "format_task_status",
    "format_timestamp",
]
