# API 覆盖与边界

快照日期：2026-08-16
官方目录：[developer.zhihu.com/docs](https://developer.zhihu.com/docs)

## 结论

知乎官方目录共有 26 条文档：3 条指南、15 条 API、4 条 Skill 和 4 条
MCP。15 条 API 实际包含 18 个数据端点；OAuth 指南另包含授权和 token
交换流程。

本项目覆盖全部 **18 个数据端点 + 2 个 OAuth 端点**。官方 Skill/MCP
以及 Zhihu CLI 与现有搜索、直答、热榜、用户数据能力重复，因此只记录，
不再递归代理。

## 端点覆盖

| 能力 | HTTP 端点 | CLI | MCP full / OpenAPI |
|---|---|---|---|
| 知乎搜索 | `GET /api/v1/content/zhihu_search` | `search --scope zhihu` | `search` |
| 全网搜索 | `GET /api/v1/content/global_search` | `search --scope web` | `search` |
| 热榜 | `GET /api/v1/content/hot_list` | `trending` | `trending` |
| 直答 | `POST /v1/chat/completions` | `ask` | `ask` |
| 用户创作 | `GET /api/v1/user/contents` | `user-contents` | `user_contents` |
| 用户关注 | `GET /api/v1/user/followees` | `user-followees` | `user_followees` |
| 近期收藏 | `GET /api/v1/user/collections` | `user-collections` | `user_collections` |
| 收藏夹列表 | `GET /api/v1/user/favlists` | `user-favlists` | `user_favlists` |
| 收藏夹内容 | `GET /api/v1/user/favlist_contents` | `favlist-contents` | `favlist_contents` |
| 知识库列表 | `GET /api/v1/knowledge/bases` | `knowledge-bases` | `knowledge_bases` |
| 知识库内容 | `GET /api/v1/knowledge/bases/{id}/items` | `knowledge-items` | `knowledge_items` |
| 知识库上传 | `POST /api/v1/knowledge/files` | `knowledge-upload` | 不暴露 |
| 知识库检索 | `POST /api/v1/knowledge/search` | `knowledge-search` | `knowledge_search` |
| PDF 上传 | `POST /resources/v1/files` | `pdf-upload` | 不暴露 |
| PDF 创建任务 | `POST /api/v1/pdf-parse/tasks` | `pdf-create` | `pdf_create` |
| PDF 状态 | `GET /api/v1/pdf-parse/tasks/{task_id}` | `pdf-status` | `pdf_status` |
| PPT 创建任务 | `POST /api/v1/ppt-generation/tasks` | `ppt-create` | `ppt_create` |
| PPT 状态 | `GET /api/v1/ppt-generation/tasks/{task_id}` | `ppt-status` | `ppt_status` |
| OAuth 授权 | `GET https://openapi.zhihu.com/authorize` | `oauth-url` | 不暴露 |
| OAuth token | `POST https://openapi.zhihu.com/access_token` | `oauth-token` | 不暴露 |

“覆盖”表示项目已有类型化调用路径。账号是否拥有接口权限，仍以知乎实际
返回为准。

## MCP 工具开关

MCP 默认使用 `compact`，避免把低频工具长期放进模型上下文：

| 档位 | 工具 |
|---|---|
| `compact` | `search`、`ask`、`trending`、`other` |
| `knowledge` | compact 加 `knowledge_bases`、`knowledge_items`、`knowledge_search` |
| `user` | compact 加 5 个 `user_*` / `favlist_contents` 工具 |
| `office` | compact 加 `pdf_create`、`pdf_status`、`ppt_create`、`ppt_status` |
| `full` | 上表 15 个业务工具，加 `other`，共 16 个 |

选择值是逗号分隔的档位名与工具名混写，结果取并集，例如 `knowledge,user`
或 `compact,knowledge_search`。只写工具名时为严格 allowlist，例如
`search,ask,pdf_status`。档位名与工具名不允许重名，避免解析时遮蔽工具。

`other` 是会话级管理工具：

- `enable` 展开 `user_contents`、`user_followees`、`user_collections`、
  `user_favlists`、`favlist_contents`、`knowledge_bases`、
  `knowledge_items`、`knowledge_search`、`pdf_create`、`pdf_status`、
  `ppt_create`、`ppt_status`。
- `disable` 收起上述 12 个工具。
- `reset` 恢复服务器启动时的工具集合。

只要选择里出现档位名，`other` 就可管理全部 12 个低频工具；纯工具名的严格
allowlist 下只能管理其中已允许的名称，无法展开列表外工具。

启动参数为 `--tools`；也可用 `ZHIHU_MCP_TOOLS` 设置默认值，命令行优先。
OpenAPI 仍直接提供 15 个业务操作，不使用 MCP 的会话级 `other`。

## 官方文档中的不确定项

| 项目 | 本项目处理 |
|---|---|
| 未说明 OAuth `state`、scope、PKCE、refresh、revoke | 不自行添加参数或端点 |
| 提到用户信息但未给 URL 或字段 | 不猜测接口 |
| `Offset` 写 Int64，`NextOffset` 写 String | 同时接受数字和不透明字符串 |
| 全网搜索返回 `HasMore`，但无 cursor | 不制造翻页参数 |
| 收藏与收藏夹列表只给 `Limit` | 不添加未文档化分页 |
| 收藏夹内容现只文档化 `FavlistUrlToken` | 仍接受旧的 `FavlistId`，但不作为推荐入口 |
| PDF Markdown 写 100MB，Playground 写 50MB | 采用正式 Markdown 的 100MB |
| 热榜 Markdown 写最大 30，Playground 写 50 | 保持正式合同的 30 |
| PDF/PPT 未给轮询间隔 | 只提供显式状态查询，不自动紧密轮询 |
| 知识库上传是同步接口，未给超时建议 | 本地等待 180 秒；超时后不自动重试 |
| 官方 Zhihu CLI / Skill / MCP | 只记录，不递归代理 |

## 安全边界

- PDF 与知识库本机路径只允许 CLI/Python 读取，MCP/OpenAPI 不接收路径。
- OAuth `app_key` 和 token 交换只允许 CLI/Python 执行。
- 用户 OAuth token 只放在服务端 `ZHIHU_OAUTH_TOKEN`；模型侧只看到
  `use_configured_oauth_user` 布尔开关。
- OpenAPI 只有配置 `--api-key` 或 `ZHIHU_OPENWEBUI_API_KEY` 时才启用
  Bearer 鉴权；无 key 模式只能用于本机或受控私网。
- 不提供任意 URL 或原始 HTTP 透传工具。
