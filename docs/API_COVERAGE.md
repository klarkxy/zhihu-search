# API 覆盖与边界

这份文档是项目的能力事实表，适合核对“某个端点是否支持、通过什么入口调用、
哪些参数不能交给模型”。如果只是想开始使用，请先看[安装与配置](../setup/README.md)：
默认选 Skill，高频使用时再配置 MCP。

快照日期：2026-09-28

官方目录：[developer.zhihu.com/docs](https://developer.zhihu.com/docs)

## 先看结论

知乎官方目录共有 33 条文档：3 条指南、22 条 API、4 条 Skill 和 4 条
MCP。22 条 API 实际包含 24 个业务端点；
[额度查询指南](https://developer.zhihu.com/docs?key=quota)另包含 1 个官方额度端点，
OAuth 指南还包含授权和 token 交换流程。

本项目覆盖全部 **25 个业务/账号端点 + 2 个 OAuth 端点**。用户默认通过本
项目的 Skill 进入；高频客户端可以选择 MCP；脚本或本机文件操作使用 CLI。

官方 Skill、MCP 和 Zhihu CLI 与本项目已有能力重复，因此这里只记录它们，
不会再套一层代理。

## 端点覆盖

| 能力 | HTTP 端点 | CLI | MCP full / OpenAPI |
|---|---|---|---|
| 知乎搜索 | `GET /api/v1/content/zhihu_search` | `search --scope zhihu` | `search` |
| 全网搜索 | `GET /api/v1/content/global_search` | `search --scope web` | `search` |
| 热榜 | `GET /api/v1/content/hot_list` | `trending` | `trending` |
| 直答 | `POST /v1/chat/completions` | `ask` | `ask` |
| 问题推荐 | `GET /api/v1/user/question_recommendations` | `question-recommendations` | `question_recommendations` |
| 问题回答摘要 | `GET /api/v1/content/question_answers` | `question-answers` | `question_answers` |
| 官方额度 | `GET /api/v1/quota` | `quota` / `--quota` | `quota` |
| 用户创作 | `GET /api/v1/user/contents` | `user-contents` | `user_contents` |
| 用户关注 | `GET /api/v1/user/followees` | `user-followees` | `user_followees` |
| 近期收藏 | `GET /api/v1/user/collections` | `user-collections` | `user_collections` |
| 收藏夹列表 | `GET /api/v1/user/favlists` | `user-favlists` | `user_favlists` |
| 收藏夹内容 | `GET /api/v1/user/favlist_contents` | `favlist-contents` | `favlist_contents` |
| 本人创作全文 | `GET /api/v1/user/content_detail` | `user-content-detail` | `user_content_detail` |
| 本人创作评论 | `GET /api/v1/user/content_comments` | `user-content-comments` | `user_content_comments` |
| 账号创作数据 | `GET /api/v1/user/creator_account_stats` | `creator-account-stats` | `creator_account_stats` |
| 单篇创作数据 | `GET /api/v1/user/creator_content_stats` | `creator-content-stats` | `creator_content_stats` |
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

这里的“覆盖”只表示项目已有类型化调用路径，不代表每个知乎账号都拥有对应
权限；最终仍以知乎返回结果为准。

## MCP 工具开关（高频集成）

MCP 是 Skill 之后的高频集成选项。默认使用 `compact`，避免把低频工具长期
放进模型上下文：

| 档位 | 工具 |
|---|---|
| `compact` | `search`、`ask`、`trending`、`other` |
| `knowledge` | compact 加 `knowledge_bases`、`knowledge_items`、`knowledge_search` |
| `user` | compact 加 5 个 `user_*` / `favlist_contents` 工具 |
| `questions` | compact 加 `question_recommendations`、`question_answers` |
| `creator` | compact 加 `user_content_detail`、`user_content_comments`、`creator_account_stats`、`creator_content_stats` |
| `office` | compact 加 `pdf_create`、`pdf_status`、`ppt_create`、`ppt_status` |
| `full` | 上表 22 个业务/账号工具，加 `other`，共 23 个 |

选择值是逗号分隔的档位名与工具名混写，结果取并集，例如 `knowledge,user`
或 `compact,knowledge_search`。只写工具名时为严格 allowlist，例如
`search,ask,pdf_status`。档位名与工具名不允许重名，避免解析时遮蔽工具。

`other` 是会话级管理工具：

- `enable` 展开 `quota`、5 个本人公开数据工具、`question_recommendations`、
  `question_answers`、`user_content_detail`、`user_content_comments`、
  `creator_account_stats`、`creator_content_stats`、`knowledge_bases`、
  `knowledge_items`、`knowledge_search`、`pdf_create`、`pdf_status`、
  `ppt_create`、`ppt_status`。
- `disable` 收起上述 19 个工具。
- `reset` 恢复服务器启动时的工具集合。

只要选择里出现档位名，`other` 就可管理全部 19 个低频工具；纯工具名的严格
allowlist 下只能管理其中已允许的名称，无法展开列表外工具。

启动参数为 `--tools`；也可用 `ZHIHU_MCP_TOOLS` 设置默认值，命令行优先。
这里的数量容易混淆：MCP `full` 是 **23 个工具**（22 个业务/账号工具加
`other`）；OpenAPI 是 **22 个业务/账号操作**，没有会话级 `other`。
搜索仍是一个工具覆盖知乎搜索和全网搜索两个端点。

## 官方文档没有说清的地方

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
| 额度文档未说明自然日的时区与重置时刻 | 不猜测倒计时，只展示官方当前值 |
| 额度筛选未说明重复 ID 的语义 | 调用前按首次出现顺序去重 |
| 问题推荐省略 `Query` 与传空字符串含义不同 | 省略参数走画像；空白字符串在本地拒绝 |
| 问题回答与评论的 `NextOffset` 为 Int64 | 只接受非负整数，不接受不透明游标 |
| `IsEnd=false` 但缺少 `NextOffset` | 展示分页不完整并停止翻页，不按条数补偏移 |
| 创作统计可选指标缺失 | 不补零，比例不换算成百分比 |
| 统计日期成对出现，省略时范围未固定 | 只在成对且 `YYYY-MM-DD` 时上传，不猜测天数 |
| 全文和评论可能含 HTML | Markdown 展示前去掉标签；JSON 保留上游原文 |
| 创作能力与问题发现不接受 OAuth 切换 | 不提供 token 参数 |
| `30003` 表示风控拒绝 | 展示上游消息，并提示不要立即重试 |
| 官方 Zhihu CLI / Skill / MCP | 只记录，不递归代理 |

## 不可越过的安全边界

- PDF 与知识库本机路径只允许 CLI/Python 读取，MCP/OpenAPI 不接收路径。
- OAuth `app_key` 和 token 交换只允许 CLI/Python 执行。
- 用户 OAuth token 只放在服务端 `ZHIHU_OAUTH_TOKEN`；模型侧只看到
  `use_configured_oauth_user` 布尔开关。
- OpenAPI 只有配置 `--api-key` 或 `ZHIHU_OPENWEBUI_API_KEY` 时才启用
  Bearer 鉴权；无 key 模式只能用于本机或受控私网。
- 不提供任意 URL 或原始 HTTP 透传工具。
- 官方额度接口是唯一额度来源；不做本地计数、预测、熔断或重置。
