"""知乎开放平台 REST 客户端。

接口规范（参见 https://developer.zhihu.com/docs）：

- 内容能力：知乎搜索、全网搜索、热榜、直答。
- 账号能力：查询官方每日额度。
- 用户能力：创作内容、关注、近期收藏、收藏夹及收藏夹内容。
- 知识库能力：列表、内容、文件上传与 RAG 检索。
- 文件能力：PDF 上传与解析任务。
- 生成能力：根据知乎回答或文章创建 PPT 任务。

公共 Header：
    Authorization: Bearer <access_secret>
    X-Request-Timestamp: <秒级 unix 时间戳>
    Content-Type: application/json

公共响应信封（除直答外的 REST 接口）：``{Code, Message, Data}``
直答响应：OpenAI Chat Completion 兼容格式。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import quote, urlparse

import httpx

from .base import (
    InvalidArguments,
    McpError,
    RateLimited,
    TokenInvalid,
    UpstreamTimeout,
    UpstreamUnavailable,
    parse_retry_after,
)

BASE_URL = "https://developer.zhihu.com"

# 知乎响应信封的错误码映射
_CODE_TO_ERROR: dict[int, type[McpError]] = {
    10001: InvalidArguments,    # 参数错误
    20001: TokenInvalid,        # 鉴权失败
    30001: RateLimited,         # 频率限制
    30002: RateLimited,         # 配额限制
    40001: InvalidArguments,    # 幂等键与请求参数冲突
    40002: InvalidArguments,    # 文件不存在、过期或不可访问
    40003: RateLimited,         # 活跃任务数超限
    40004: InvalidArguments,    # 知识库不存在
    40005: InvalidArguments,    # 相同文件正在处理中
    40006: InvalidArguments,    # 文件解析失败
    50002: UpstreamUnavailable, # 知识库检索失败
    90001: UpstreamUnavailable, # 内部错误
}

# 直答模型档位（OpenAI 兼容）
ZhidaModel = Literal["zhida-fast-1p5", "zhida-thinking-1p5", "zhida-agent"]
UserContentType = Literal[
    "all", "answer", "article", "zvideo", "pin", "question"
]
UserSortField = Literal["like_count", "ts"]
SortOrder = Literal["asc", "desc"]
KnowledgeScope = Literal["all", "created", "subscribed"]
KnowledgeRecallScope = Literal["personal", "subscription", "public"]
OfficialQuotaId = Literal[
    "global_search",
    "zhihu_search",
    "hot_list",
    "user_data",
    "zhida_openai",
    "knowledge",
    "tools",
]

# 各接口的参数上下界
ZHIHU_SEARCH_MAX = 10
GLOBAL_SEARCH_MAX = 20
HOT_LIST_MAX = 30
USER_PAGE_MAX = 50
KNOWLEDGE_ITEMS_MAX = 20
KNOWLEDGE_SEARCH_MAX = 10
PDF_MAX_BYTES = 100 * 1024 * 1024
KNOWLEDGE_FILE_MAX_BYTES = 100 * 1024 * 1024
KNOWLEDGE_FILENAME_MAX_BYTES = 255
QUERY_MIN = 2
QUERY_MAX = 100
INT64_MAX = (1 << 63) - 1
OFFICIAL_QUOTA_IDS: tuple[OfficialQuotaId, ...] = (
    "global_search",
    "zhihu_search",
    "hot_list",
    "user_data",
    "zhida_openai",
    "knowledge",
    "tools",
)

DEFAULT_TIMEOUT = 30.0
ZHIDA_TIMEOUT = 120.0  # agent 模型可能慢
KNOWLEDGE_UPLOAD_TIMEOUT = 180.0  # 同步解析，大文件可能较慢

_USER_CONTENT_TYPES = frozenset(
    {"all", "answer", "article", "zvideo", "pin", "question"}
)
_USER_SORT_FIELDS = frozenset({"like_count", "ts"})
_SORT_ORDERS = frozenset({"asc", "desc"})
_KNOWLEDGE_SCOPES = frozenset({"all", "created", "subscribed"})
_KNOWLEDGE_RECALL_SCOPES = frozenset({"personal", "subscription", "public"})
_KNOWLEDGE_FILE_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".md",
        ".txt",
        ".ppt",
        ".pptx",
        ".xlsx",
        ".xls",
        ".docx",
        ".doc",
        ".webp",
        ".png",
        ".jpg",
        ".mobi",
        ".epub",
        ".csv",
        ".azw3",
    }
)
_KNOWLEDGE_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    ".xls": "application/vnd.ms-excel",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".doc": "application/msword",
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".mobi": "application/x-mobipocket-ebook",
    ".epub": "application/epub+zip",
    ".csv": "text/csv",
    ".azw3": "application/vnd.amazon.ebook",
}
_ZHIHU_ANSWER_PATHS = (
    re.compile(r"^/answer/[0-9]+/?$"),
    re.compile(r"^/question/[0-9]+/answer/[0-9]+/?$"),
)
_ZHIHU_ARTICLE_PATH = re.compile(r"^/p/[0-9]+/?$")
_PDF_TASK_ID = re.compile(r"^pdf_[A-Za-z0-9_-]+$")
_PPT_TASK_ID = re.compile(r"^ppt_[A-Za-z0-9_-]+$")


@dataclass
class ApiResult:
    """一次调用后的完整结果：业务数据 + 响应头。

    ``headers`` 里如果知乎返回了限流相关头（X-RateLimit-* 等），
    会原样带上，方便上层透传给用户。
    """

    data: Any
    headers: dict[str, str]


class ZhihuRestClient:
    """一个实例覆盖知乎开放平台数据接口并共享连接池。"""

    def __init__(
        self,
        access_secret: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._access_secret = access_secret
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(
            timeout=timeout, base_url=BASE_URL
        )
        self._owns_client = client is None

    # ------------------------------------------------------------------
    # 公共：构造请求 / 解析响应
    # ------------------------------------------------------------------

    def _headers(
        self,
        *,
        oauth_token: str | None = None,
        idempotency_key: str | None = None,
        content_type: str | None = "application/json",
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._access_secret}",
            "X-Request-Timestamp": str(int(time.time())),
            "Accept": "application/json",
        }
        if content_type is not None:
            headers["Content-Type"] = content_type
        if oauth_token:
            headers["X-OAuth-Token"] = oauth_token
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def _envelope_get(
        self,
        path: str,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
        oauth_token: str | None = None,
    ) -> ApiResult:
        try:
            resp = await self._client.get(
                path,
                params=params,
                headers=self._headers(oauth_token=oauth_token),
                timeout=timeout or self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout(f"{path} 请求超时") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"{path} 网络错误：{exc}") from exc
        return self._parse_envelope(resp, path)

    async def _envelope_post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        timeout: float | None = None,
        idempotency_key: str | None = None,
    ) -> ApiResult:
        try:
            resp = await self._client.post(
                path,
                json=body,
                headers=self._headers(idempotency_key=idempotency_key),
                timeout=timeout or self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout(f"{path} 请求超时") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"{path} 网络错误：{exc}") from exc
        return self._parse_envelope(resp, path)

    def _parse_envelope(
        self,
        resp: httpx.Response,
        path: str,
    ) -> ApiResult:
        """解析 ``{Code, Message, Data}`` 信封。直答走 OpenAI 格式，单独处理。"""
        # HTTP 层错误
        if resp.status_code in (401, 403):
            raise TokenInvalid()
        if resp.status_code == 429:
            retry = parse_retry_after(resp.headers.get("Retry-After"))
            raise RateLimited(
                f"{path} 被限流（HTTP 429），retry-after={retry}s",
                retry_after=retry,
            )
        if resp.status_code >= 500:
            raise UpstreamUnavailable(f"{path} 服务端错误 HTTP {resp.status_code}")

        try:
            body = resp.json()
        except Exception as exc:
            if resp.status_code >= 400:
                raise UpstreamUnavailable(
                    f"{path} HTTP {resp.status_code}：{resp.text[:200]}"
                ) from exc
            raise UpstreamUnavailable(
                f"{path} 响应非 JSON：{resp.text[:200]}"
            ) from exc
        if resp.status_code >= 400 and not (
            isinstance(body, dict) and "Code" in body
        ):
            raise UpstreamUnavailable(
                f"{path} HTTP {resp.status_code}：{resp.text[:200]}"
            )

        if not isinstance(body, dict):
            raise UpstreamUnavailable(f"{path} 响应必须是 JSON 对象")
        code = body.get("Code")
        if code is None:
            # 不是信封格式（说明是直答，走 OpenAI chat 流程）
            raise InvalidArguments(
                f"{path} 响应缺少 Code 字段，可能不是信封接口"
            )
        try:
            numeric_code = int(code)
        except (TypeError, ValueError) as exc:
            raise UpstreamUnavailable(
                f"{path} 返回了无法识别的错误码：{code!r}"
            ) from exc
        if numeric_code != 0:
            err_cls = _CODE_TO_ERROR.get(numeric_code, UpstreamUnavailable)
            msg = body.get("Message") or "未知错误"
            if err_cls is RateLimited:
                retry = parse_retry_after(resp.headers.get("Retry-After"))
                raise RateLimited(
                    f"{path} 限流：{msg}",
                    retry_after=retry,
                )
            if err_cls is TokenInvalid:
                raise TokenInvalid()
            if err_cls is InvalidArguments:
                raise InvalidArguments(f"{path} 参数错误：{msg}")
            raise UpstreamUnavailable(f"{path} 返回错误 {numeric_code}：{msg}")

        return ApiResult(
            data=body.get("Data", {}),
            headers={k: v for k, v in resp.headers.items()},
        )

    # ------------------------------------------------------------------
    # 核心与账号接口
    # ------------------------------------------------------------------

    async def zhihu_search(
        self, query: str, count: int = 10
    ) -> ApiResult:
        """知乎站内搜索。count 超上限取 10，非正数回退默认值 10。"""
        self._validate_query(query)
        count = (
            ZHIHU_SEARCH_MAX
            if count <= 0
            else min(ZHIHU_SEARCH_MAX, count)
        )
        return await self._envelope_get(
            "/api/v1/content/zhihu_search",
            {"Query": query, "Count": count},
        )

    async def global_search(
        self,
        query: str,
        count: int = 10,
        filter: str = "",
        search_db: Literal["all", "realtime", "static"] = "all",
    ) -> ApiResult:
        """全网搜索。count 自动截断到 1-20。filter 为空时不传。"""
        self._validate_query(query)
        count = max(1, min(GLOBAL_SEARCH_MAX, count))
        params: dict[str, Any] = {"Query": query, "Count": count, "SearchDB": search_db}
        if filter:
            params["Filter"] = filter
        return await self._envelope_get("/api/v1/content/global_search", params)

    async def hot_list(self, limit: int = 30) -> ApiResult:
        """知乎热榜。limit 不在 1-30 时回退默认值 30。"""
        if limit <= 0 or limit > HOT_LIST_MAX:
            limit = HOT_LIST_MAX
        return await self._envelope_get(
            "/api/v1/content/hot_list", {"Limit": limit}
        )

    async def quota(
        self,
        api_ids: list[OfficialQuotaId] | None = None,
    ) -> ApiResult:
        """查询当前 Access Secret 的官方自然日额度。

        该接口本身不消耗业务额度。``api_ids`` 为空时返回全部可展示额度项。
        """
        params: dict[str, Any] = {}
        if api_ids:
            unknown = [
                api_id for api_id in api_ids if api_id not in OFFICIAL_QUOTA_IDS
            ]
            if unknown:
                raise InvalidArguments(
                    "未知官方额度项：" + ", ".join(dict.fromkeys(unknown))
                )
            params["APIIDs"] = ",".join(dict.fromkeys(api_ids))
        return await self._envelope_get("/api/v1/quota", params)

    # ------------------------------------------------------------------
    # 用户数据接口
    # ------------------------------------------------------------------

    async def user_contents(
        self,
        *,
        content_type: UserContentType = "all",
        offset: int | str = 0,
        limit: int = 20,
        sort_field: UserSortField = "ts",
        sort_order: SortOrder = "desc",
        oauth_token: str | None = None,
    ) -> ApiResult:
        """获取用户公开创作内容。

        不传 ``oauth_token`` 时查询调用方本人；传入时查询该 OAuth 凭证
        对应的已授权用户。``offset`` 可直接使用响应里的字符串
        ``Paging.NextOffset``。
        """
        if (
            not isinstance(content_type, str)
            or content_type not in _USER_CONTENT_TYPES
        ):
            raise InvalidArguments(
                "content_type 必须是 all、answer、article、zvideo、pin 或 question"
            )
        if not isinstance(sort_field, str) or sort_field not in _USER_SORT_FIELDS:
            raise InvalidArguments("sort_field 必须是 like_count 或 ts")
        if not isinstance(sort_order, str) or sort_order not in _SORT_ORDERS:
            raise InvalidArguments("sort_order 必须是 asc 或 desc")
        self._validate_offset(offset)
        self._validate_limit(limit, maximum=USER_PAGE_MAX)
        return await self._envelope_get(
            "/api/v1/user/contents",
            {
                "Offset": offset,
                "Limit": limit,
                "ContentType": content_type,
                "SortField": sort_field,
                "SortOrder": sort_order,
            },
            oauth_token=oauth_token,
        )

    async def user_followees(
        self,
        *,
        offset: int | str = 0,
        limit: int = 20,
        oauth_token: str | None = None,
    ) -> ApiResult:
        """获取用户公开关注列表。"""
        self._validate_offset(offset)
        self._validate_limit(limit, maximum=USER_PAGE_MAX)
        return await self._envelope_get(
            "/api/v1/user/followees",
            {"Offset": offset, "Limit": limit},
            oauth_token=oauth_token,
        )

    async def user_collections(
        self,
        *,
        limit: int = 20,
        oauth_token: str | None = None,
    ) -> ApiResult:
        """获取用户近期公开收藏内容。"""
        self._validate_limit(limit)
        return await self._envelope_get(
            "/api/v1/user/collections",
            {"Limit": limit},
            oauth_token=oauth_token,
        )

    async def user_favlists(
        self,
        *,
        limit: int = 20,
        oauth_token: str | None = None,
    ) -> ApiResult:
        """获取用户公开收藏夹列表。"""
        self._validate_limit(limit)
        return await self._envelope_get(
            "/api/v1/user/favlists",
            {"Limit": limit},
            oauth_token=oauth_token,
        )

    async def favlist_contents(
        self,
        *,
        favlist_url_token: int | None = None,
        favlist_id: int | None = None,
        offset: int | str = 0,
        limit: int = 20,
        oauth_token: str | None = None,
    ) -> ApiResult:
        """获取指定收藏夹的公开内容。

        ``favlist_url_token`` 与 ``favlist_id`` 必须且只能提供一个。
        """
        if (favlist_url_token is None) == (favlist_id is None):
            raise InvalidArguments(
                "favlist_url_token 与 favlist_id 必须且只能提供一个"
            )
        self._validate_offset(offset)
        self._validate_limit(limit)
        params: dict[str, Any] = {"Offset": offset, "Limit": limit}
        if favlist_url_token is not None:
            self._validate_positive_int(
                favlist_url_token, name="favlist_url_token"
            )
            params["FavlistUrlToken"] = favlist_url_token
        else:
            assert favlist_id is not None
            self._validate_positive_int(favlist_id, name="favlist_id")
            params["FavlistId"] = favlist_id
        return await self._envelope_get(
            "/api/v1/user/favlist_contents",
            params,
            oauth_token=oauth_token,
        )

    # ------------------------------------------------------------------
    # 知识库
    # ------------------------------------------------------------------

    async def knowledge_bases(
        self,
        *,
        scope: KnowledgeScope = "all",
    ) -> ApiResult:
        """获取当前用户创建或订阅的知识库。"""
        if not isinstance(scope, str) or scope not in _KNOWLEDGE_SCOPES:
            raise InvalidArguments("scope 必须是 all、created 或 subscribed")
        return await self._envelope_get(
            "/api/v1/knowledge/bases",
            {"Scope": scope},
        )

    async def knowledge_items(
        self,
        knowledge_base_id: str,
        *,
        cursor: str = "",
        limit: int = 20,
    ) -> ApiResult:
        """分页获取指定知识库中的内容。``cursor`` 可直接使用上一页的 ``NextCursor``。"""
        self._validate_knowledge_base_id(knowledge_base_id)
        self._validate_limit(limit, maximum=KNOWLEDGE_ITEMS_MAX)
        params: dict[str, Any] = {"Limit": limit}
        if cursor:
            self._validate_nonempty_string(cursor, name="cursor")
            params["Cursor"] = cursor
        encoded_id = quote(knowledge_base_id, safe="")
        return await self._envelope_get(
            f"/api/v1/knowledge/bases/{encoded_id}/items",
            params,
        )

    async def upload_knowledge_file(
        self,
        file_path: str | Path,
        *,
        knowledge_base_id: str | None = None,
    ) -> ApiResult:
        """上传文件并同步完成解析和知识库挂载。

        不指定 ``knowledge_base_id`` 时进入当前用户的默认知识库。该接口是
        同步接口，较大文件可能较慢；超时或未知结果不要自动重试。
        """
        try:
            path = Path(file_path)
            stat = path.stat()
        except (OSError, TypeError, ValueError) as exc:
            raise InvalidArguments(f"知识库文件不可访问：{file_path}") from exc
        if not path.is_file():
            raise InvalidArguments(f"知识库路径不是文件：{path}")
        if stat.st_size <= 0:
            raise InvalidArguments("知识库文件内容不能为空")
        if stat.st_size > KNOWLEDGE_FILE_MAX_BYTES:
            raise InvalidArguments("知识库文件大小不能超过 100MB")

        filename = self._validate_knowledge_filename(path.name)
        suffix = Path(filename).suffix.lower()
        if suffix not in _KNOWLEDGE_FILE_EXTENSIONS:
            raise InvalidArguments(
                "知识库上传仅支持 pdf、md、txt、ppt、pptx、xlsx、xls、"
                "docx、doc、webp、png、jpg、mobi、epub、csv、azw3"
            )
        if knowledge_base_id is not None:
            self._validate_knowledge_base_id(knowledge_base_id)

        content_type = _KNOWLEDGE_CONTENT_TYPES.get(
            suffix, "application/octet-stream"
        )
        data: dict[str, str] | None = None
        if knowledge_base_id is not None:
            data = {"KnowledgeBaseID": knowledge_base_id}

        try:
            with path.open("rb") as stream:
                resp = await self._client.post(
                    "/api/v1/knowledge/files",
                    data=data,
                    files={
                        "File": (filename, stream, content_type),
                    },
                    headers=self._headers(content_type=None),
                    timeout=KNOWLEDGE_UPLOAD_TIMEOUT,
                )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout(
                f"/api/v1/knowledge/files 请求超时（>{KNOWLEDGE_UPLOAD_TIMEOUT}s）；"
                "请不要对超时或未知结果自动重试"
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                f"/api/v1/knowledge/files 网络错误：{exc}"
            ) from exc
        except OSError as exc:
            raise InvalidArguments(f"读取知识库文件失败：{path}") from exc
        return self._parse_envelope(resp, "/api/v1/knowledge/files")

    async def knowledge_search(
        self,
        query: str,
        *,
        knowledge_base_ids: list[str] | None = None,
        recall_scopes: list[KnowledgeRecallScope] | None = None,
        limit: int = 10,
    ) -> ApiResult:
        """使用 RAG 从指定知识库或召回范围中检索相关文档片段。"""
        if not isinstance(query, str):
            raise InvalidArguments("query 不能为空")
        query = query.strip()
        self._validate_nonempty_string(query, name="query")
        self._validate_limit(limit, maximum=KNOWLEDGE_SEARCH_MAX)

        ids = self._normalize_knowledge_base_ids(knowledge_base_ids)
        scopes = self._normalize_recall_scopes(recall_scopes)
        if not ids and not scopes:
            raise InvalidArguments(
                "KnowledgeBaseIDs 与 RecallScopes 至少需要提供一个非空值"
            )

        body: dict[str, Any] = {"Query": query, "Limit": limit}
        if ids:
            body["KnowledgeBaseIDs"] = ids
        if scopes:
            body["RecallScopes"] = scopes
        return await self._envelope_post(
            "/api/v1/knowledge/search",
            body,
        )

    # ------------------------------------------------------------------
    # PDF 解析与 PPT 生成
    # ------------------------------------------------------------------

    async def upload_pdf(self, file_path: str | Path) -> ApiResult:
        """上传一个不超过 100MB 的本地 PDF，并返回 ``file_id``。"""
        try:
            path = Path(file_path)
            stat = path.stat()
        except (OSError, TypeError, ValueError) as exc:
            raise InvalidArguments(f"PDF 文件不可访问：{file_path}") from exc
        if not path.is_file():
            raise InvalidArguments(f"PDF 路径不是文件：{path}")
        if path.suffix.lower() != ".pdf":
            raise InvalidArguments("当前上传接口仅支持 .pdf 文件")
        if stat.st_size > PDF_MAX_BYTES:
            raise InvalidArguments("PDF 文件大小不能超过 100MB")

        try:
            with path.open("rb") as stream:
                resp = await self._client.post(
                    "/resources/v1/files",
                    files={
                        "file": (
                            path.name,
                            stream,
                            "application/pdf",
                        )
                    },
                    headers=self._headers(content_type=None),
                    timeout=self._timeout,
                )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout("/resources/v1/files 请求超时") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                f"/resources/v1/files 网络错误：{exc}"
            ) from exc
        except OSError as exc:
            raise InvalidArguments(f"读取 PDF 文件失败：{path}") from exc
        return self._parse_envelope(resp, "/resources/v1/files")

    async def create_pdf_parse_task(
        self,
        file_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> ApiResult:
        """用上传接口返回的 ``file_id`` 创建 PDF 解析任务。"""
        self._validate_nonempty_string(file_id, name="file_id")
        return await self._envelope_post(
            "/api/v1/pdf-parse/tasks",
            {"file_id": file_id},
            idempotency_key=idempotency_key,
        )

    async def get_pdf_parse_task(self, task_id: str) -> ApiResult:
        """查询 PDF 解析任务状态。"""
        self._validate_task_id(task_id, kind="PDF")
        return await self._envelope_get(
            f"/api/v1/pdf-parse/tasks/{task_id}",
            {},
        )

    async def create_ppt_generation_task(
        self,
        resource_url: str,
        num_pages: int = 12,
        *,
        idempotency_key: str | None = None,
    ) -> ApiResult:
        """根据知乎回答或文章链接创建 6-21 页的 PPT 生成任务。"""
        self._validate_zhihu_resource_url(resource_url)
        if (
            isinstance(num_pages, bool)
            or not isinstance(num_pages, int)
            or not 6 <= num_pages <= 21
        ):
            raise InvalidArguments("num_pages 必须是 6-21 之间的整数")
        return await self._envelope_post(
            "/api/v1/ppt-generation/tasks",
            {"resource_url": resource_url, "num_pages": num_pages},
            idempotency_key=idempotency_key,
        )

    async def get_ppt_generation_task(self, task_id: str) -> ApiResult:
        """查询 PPT 生成任务状态。"""
        self._validate_task_id(task_id, kind="PPT")
        return await self._envelope_get(
            f"/api/v1/ppt-generation/tasks/{task_id}",
            {},
        )

    async def zhida(
        self,
        query: str,
        model: ZhidaModel = "zhida-fast-1p5",
        stream: bool = False,
    ) -> ApiResult:
        """知乎直答。OpenAI 兼容 chat completions 接口。

        返回结构会被规整成统一信封：
            data = {
                "id": "...",
                "model": "...",
                "content": "<最终回答>",
                "reasoning_content": "<思考过程，可能为空>",
                "finish_reason": "stop",
            }
        """
        if not query.strip():
            raise InvalidArguments("直答的 query 不能为空")

        body = {
            "model": model,
            "messages": [{"role": "user", "content": query}],
            "stream": stream,
        }
        # 直答不返回信封，走 OpenAI chat 格式，单独解析
        try:
            resp = await self._client.post(
                "/v1/chat/completions",
                json=body,
                headers=self._headers(),
                timeout=ZHIDA_TIMEOUT,
            )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout(
                f"直答请求超时（>{ZHIDA_TIMEOUT}s）；如使用 agent 模型请改 fast"
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"直答网络错误：{exc}") from exc

        if resp.status_code in (401, 403):
            raise TokenInvalid()
        if resp.status_code == 429:
            retry = parse_retry_after(resp.headers.get("Retry-After"))
            raise RateLimited(
                f"直答限流，retry-after={retry}s",
                retry_after=retry,
            )
        if resp.status_code >= 400:
            raise UpstreamUnavailable(
                f"直答 HTTP {resp.status_code}：{resp.text[:200]}"
            )

        try:
            payload = resp.json()
        except Exception as exc:
            raise UpstreamUnavailable(
                f"直答响应非 JSON：{resp.text[:200]}"
            ) from exc

        if "error" in payload:
            err = payload["error"]
            raise UpstreamUnavailable(f"直答错误：{err.get('message', err)}")

        choices = payload.get("choices") or []
        if not choices:
            raise UpstreamUnavailable("直答返回为空 choices")
        msg = choices[0].get("message") or {}
        normalized = {
            "id": payload.get("id"),
            "model": payload.get("model"),
            "content": msg.get("content", ""),
            "reasoning_content": msg.get("reasoning_content", ""),
            "finish_reason": choices[0].get("finish_reason"),
        }

        return ApiResult(
            data=normalized,
            headers={k: v for k, v in resp.headers.items()},
        )

    # ------------------------------------------------------------------
    # 资源管理
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "ZhihuRestClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_query(query: str) -> None:
        if not (QUERY_MIN <= len(query) <= QUERY_MAX):
            raise InvalidArguments(
                f"query 长度需在 {QUERY_MIN}-{QUERY_MAX} 字符之间（当前 {len(query)}）"
            )

    @staticmethod
    def _validate_offset(offset: int | str) -> None:
        if isinstance(offset, bool):
            raise InvalidArguments("offset 必须是非负整数或非空字符串")
        if isinstance(offset, int):
            if not 0 <= offset <= INT64_MAX:
                raise InvalidArguments("offset 超出 Int64 非负整数范围")
        elif isinstance(offset, str) and offset:
            return
        else:
            raise InvalidArguments("offset 必须是非负整数或非空字符串")

    @staticmethod
    def _validate_limit(limit: int, *, maximum: int | None = None) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 1
            or limit > INT64_MAX
        ):
            raise InvalidArguments("limit 必须是正整数")
        if maximum is not None and limit > maximum:
            raise InvalidArguments(f"limit 不能超过 {maximum}")

    @staticmethod
    def _validate_positive_int(value: int, *, name: str) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= INT64_MAX
        ):
            raise InvalidArguments(f"{name} 必须是 Int64 范围内的正整数")

    @staticmethod
    def _validate_nonempty_string(value: str, *, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise InvalidArguments(f"{name} 不能为空")

    @classmethod
    def _validate_knowledge_base_id(cls, knowledge_base_id: str) -> None:
        cls._validate_nonempty_string(
            knowledge_base_id, name="knowledge_base_id"
        )

    @staticmethod
    def _validate_knowledge_filename(name: str) -> str:
        cleaned = Path(name).name.strip()
        if not cleaned:
            raise InvalidArguments("知识库文件名不能为空")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
            raise InvalidArguments("知识库文件名不能包含控制字符")
        if len(cleaned.encode("utf-8")) > KNOWLEDGE_FILENAME_MAX_BYTES:
            raise InvalidArguments("知识库文件名不能超过 255 个 UTF-8 字节")
        return cleaned

    @classmethod
    def _normalize_knowledge_base_ids(
        cls, knowledge_base_ids: list[str] | None
    ) -> list[str]:
        if knowledge_base_ids is None:
            return []
        if not isinstance(knowledge_base_ids, list):
            raise InvalidArguments("knowledge_base_ids 必须是字符串列表")
        normalized: list[str] = []
        for item in knowledge_base_ids:
            cls._validate_knowledge_base_id(item)
            normalized.append(item.strip())
        return normalized

    @staticmethod
    def _normalize_recall_scopes(
        recall_scopes: list[KnowledgeRecallScope] | None,
    ) -> list[str]:
        if recall_scopes is None:
            return []
        if not isinstance(recall_scopes, list):
            raise InvalidArguments("recall_scopes 必须是字符串列表")
        normalized: list[str] = []
        for item in recall_scopes:
            if not isinstance(item, str) or item not in _KNOWLEDGE_RECALL_SCOPES:
                raise InvalidArguments(
                    "recall_scopes 只能包含 personal、subscription 或 public"
                )
            normalized.append(item)
        return normalized

    @staticmethod
    def _validate_task_id(task_id: str, *, kind: Literal["PDF", "PPT"]) -> None:
        pattern = _PDF_TASK_ID if kind == "PDF" else _PPT_TASK_ID
        if not isinstance(task_id, str) or pattern.fullmatch(task_id) is None:
            prefix = "pdf_" if kind == "PDF" else "ppt_"
            raise InvalidArguments(
                f"{kind} task_id 必须以 {prefix} 开头，且只能包含"
                " ASCII 字母、数字、下划线和连字符"
            )

    @classmethod
    def _validate_zhihu_resource_url(cls, resource_url: str) -> None:
        cls._validate_nonempty_string(resource_url, name="resource_url")
        try:
            parsed = urlparse(resource_url)
            hostname = parsed.hostname
        except ValueError as exc:
            raise InvalidArguments("resource_url 不是有效 URL") from exc
        if parsed.scheme != "https" or hostname is None:
            raise InvalidArguments("resource_url 必须是 HTTPS 知乎链接")
        if hostname == "www.zhihu.com" and any(
            pattern.fullmatch(parsed.path) for pattern in _ZHIHU_ANSWER_PATHS
        ):
            return
        if (
            hostname == "zhuanlan.zhihu.com"
            and _ZHIHU_ARTICLE_PATH.fullmatch(parsed.path)
        ):
            return
        raise InvalidArguments(
            "resource_url 仅支持知乎回答或知乎专栏文章链接"
        )


__all__ = [
    "ZhihuRestClient",
    "ApiResult",
    "ZhidaModel",
    "UserContentType",
    "UserSortField",
    "SortOrder",
    "KnowledgeScope",
    "KnowledgeRecallScope",
    "ZHIHU_SEARCH_MAX",
    "GLOBAL_SEARCH_MAX",
    "HOT_LIST_MAX",
    "USER_PAGE_MAX",
    "KNOWLEDGE_ITEMS_MAX",
    "KNOWLEDGE_SEARCH_MAX",
    "PDF_MAX_BYTES",
    "KNOWLEDGE_FILE_MAX_BYTES",
    "QUERY_MIN",
    "QUERY_MAX",
]
