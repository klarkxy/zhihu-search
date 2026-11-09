"""知乎同步：把已有内容适配成文章、提问或想法，预览后经确认发布。

规则来自知乎官方「知乎同步助手」（仓库 `Zhihu/ZhihuSync`，MIT，author zhihu）：
草稿、校验、预览、确认后调用 ``POST /openapi/publish``。本包是独立实现，
供 CLI、Python 与可选 MCP 档位 ``sync`` 使用，不逐字复制上游 Skill 正文。

发布凭证是 ``ZHIHU_OPENAPI_APP_KEY`` / ``ZHIHU_OPENAPI_APP_SECRET``，
与搜索用的 Access Secret 无关。密钥不能作为工具参数，也不能出现在返回值里。
"""

from __future__ import annotations

from .content import build_publish_request, prepare_content
from .service import (
    SyncServiceError,
    get_draft,
    list_drafts,
    prepare_saved,
    preview_draft,
    publish_draft,
    save_draft,
    upload_image,
)

__all__ = [
    "SyncServiceError",
    "build_publish_request",
    "get_draft",
    "list_drafts",
    "prepare_content",
    "prepare_saved",
    "preview_draft",
    "publish_draft",
    "save_draft",
    "upload_image",
]
