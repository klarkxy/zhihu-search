# API 覆盖与边界

这份文档是项目的能力事实表，适合核对“某个端点是否支持、通过什么入口调用、
哪些参数不能交给模型”。如果只是想开始使用，请先看[安装与配置](../setup/README.md)：
默认选 Skill，高频使用时再配置 MCP。

接口清单快照：2026-09-28；额度与调用保护更新：2026-10-13

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
| `sync` | compact 加 `sync_save`、`sync_list`、`sync_get`、`sync_prepare`、`sync_preview`、`sync_publish`、`sync_upload_image` |
| `full` | 上表 22 个上游业务/账号工具，加 `research`、`research_render` 和 `other`，共 25 个。不含 `sync` |

选择值是逗号分隔的档位名与工具名混写，结果取并集，例如 `knowledge,user`
或 `compact,knowledge_search`。只写工具名时为严格 allowlist，例如
`search,ask,pdf_status`。档位名与工具名不允许重名，避免解析时遮蔽工具。

`other` 是会话级管理工具：

- `enable` 展开 `quota`、5 个本人公开数据工具、`question_recommendations`、
  `question_answers`、`user_content_detail`、`user_content_comments`、
  `creator_account_stats`、`creator_content_stats`、`knowledge_bases`、
  `knowledge_items`、`knowledge_search`、`pdf_create`、`pdf_status`、
  `ppt_create`、`ppt_status`、`research`、`research_render`。
- `disable` 收起上述 21 个工具。
- `reset` 恢复服务器启动时的工具集合。

只要选择里出现档位名，`other` 就可管理全部 21 个低频工具；纯工具名的严格
allowlist 下只能管理其中已允许的名称，无法展开列表外工具。

启动参数为 `--tools`；也可用 `ZHIHU_MCP_TOOLS` 设置默认值，命令行优先。
这里的数量容易混淆：MCP `full` 是 **25 个工具**（22 个上游业务/账号工具、
本地的 `research` 与 `research_render`，再加 `other`）；OpenAPI 是 **24 个操作**，
其中 `/research` 和 `/research/render` 不是新的知乎端点。
搜索仍是一个工具覆盖知乎搜索和全网搜索两个端点。`sync` 是另一组 7 个工具，
默认不加载，`other` 也不会展开。

## 研究证据、宿主综合与本地报告

深度研究、知乎观察和近况速览没有单独的官方 HTTP 端点。公开材料把它们描述成
检索之后再写报告和本地交互页。本仓库用已有客户端完成检索，再由宿主写结构、
由本地渲染器校验。官方 Skill、渲染脚本和样式没有再分发许可，这里不复制。

公开依据：

- [Zhihu CLI 文档](https://developer.zhihu.com/docs?key=zhihu_cli)
- [全网搜索](https://developer.zhihu.com/api/v1/content/global_search)：`SearchDB` 为 `all`、`realtime` 或 `static`；`Filter` 的官方示例是 `host=="example.com" AND publish_time>=1778494631`（操作符两侧不加空格，站点加双引号，时间戳不加引号，`AND`/`OR` 大写）；最多 20 条；`HasMore` 没有请求用的 cursor；返回的 `EditTime` 是最后编辑时间，不是 `publish_time` 过滤证明；`AuthorityLevel` 字符串 `1` 低、`2` 中、`3` 高、`4` 很高只记载在全网搜索
- [知乎搜索](https://developer.zhihu.com/api/v1/content/zhihu_search)：最多 10 条；会返回 `AuthorityLevel`，但该页没有 1-4 图例，本仓库不套用；`EditTime` 是发布或更新时间
- 产品介绍文章：<https://zhuanlan.zhihu.com/p/2103916806142259391>

| 步骤 | 谁做 | 入口 |
|---|---|---|
| 检索 | 工具，走现有额度预查、每日上限、失败即停 | `research deep\|observe\|recent`，或 MCP / OpenAPI `research` |
| 综合 | 宿主。工具不调用直答，也不生成结论 | 按 `zhihu-search.report.v1` 写 JSON |
| 校验和渲染 | 工具。不访问网络 | `research-render EVIDENCE.json SYNTHESIS.json --out DIR` |

三种工作流：

- `deep`：默认知乎加全网。知识库只在显式给出已有知识库或召回范围时检索。宿主写场景、条件结论、规格与体验、争议。交互数字必须出现在证据摘录里，或带假设编号；公式不能写死数字。
- `observe`：默认只查知乎，并默认再取最多两个问题的一页回答摘要。摘要不是全文。观点并列，样本不能写成全体用户观点。作者和赞同数只有上游真的返回才保留。
- `recent`：默认窗口是截至本次时钟的滚动 30 个 86400 秒。全网使用 `SearchDB=realtime` 和 `publish_time` 下界；知乎搜索没有日期参数。发布或更新时间和事件日期分开。缺日期或对不上摘录的日期进入不确定列表，不进入确认时间线。搜索排名不当成时间。

证据包的 `report` 和 `html` 固定是 null。空证据、未完成检索上的 complete 报告、没有出处的数字、以及全体用户式表述都会使渲染失败，并且不会写出看起来已经完成的文件。

单次 `max_calls` 默认 6、最大 12。它不改变 `ZHIHU_ALLOW_PAID` 或 `ZHIHU_DAILY_CALL_LIMIT`，模型参数里也没有这两项。渲染结果 `publishable` 为 false，不能拿去 `sync-publish`。

离线验证：

```bash
uv run pytest tests/test_research.py tests/test_call_policy.py
```

这些测试使用 mock。研究检索的额度预检和每日上限断言在 `test_call_policy.py`，
因为其他测试文件会短路调用保护。它们不读取本机 Access Secret，也不请求知乎。
仓库里的 GitHub workflow 只在打 tag 或手动触发时跑测试。开放 PR 上 0 个检查
不表示 CI 已通过，只表示没有挂检查。上面的 pytest 是本地结果。

## 知乎同步发布

这不是上面那 25 个 Bearer 端点。文章、提问和想法走知乎同步助手的发布
OpenAPI，HMAC-SHA256 签名，主机固定为 `https://openapi.zhihu.com`：

| 能力 | HTTP | CLI | MCP `sync` |
|---|---|---|---|
| 发布 | `POST /openapi/publish` | `sync-publish --confirm` | `sync_publish` |
| 图片上传 | `POST /openapi/media/uploads` 及后续直传、提交、水印 | `sync-upload-image` | `sync_upload_image`（base64，不接收本地路径） |
| 草稿、校验、预览 | 本地 | `sync-save`、`sync-list`、`sync-get`、`sync-prepare`、`sync-preview` | 同名下划线工具 |

凭证是 `ZHIHU_OPENAPI_APP_KEY` 与 `ZHIHU_OPENAPI_APP_SECRET`，申请页为
<https://www.zhihu.com/playground/zhihu-sync>。规则来自知乎官方同步助手
（[Zhihu/ZhihuSync](https://github.com/Zhihu/ZhihuSync)，MIT，author zhihu），
本仓库是独立实现。发布必须先校验和预览，并且用户明确确认；不确定的结果会锁住
草稿，不会自动重试。它不走搜索接口的免费额度预检，本机另有北京时间每天 50 次
发布尝试上限。OpenWebUI 不暴露这组能力。密钥不能作为工具参数，也不能出现在
输出里。

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
| 每日免费额度按北京时间 00:00 重置 | 官方当前值与本地每日保护计数分别展示 |
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
- 发布 OpenAPI 的 App Secret 只从环境变量或本机凭证文件读取。MCP 不接收它，
  发布工具还必须带上用户确认和当次预览令牌。
- 用户 OAuth token 只放在服务端 `ZHIHU_OAUTH_TOKEN`；模型侧只看到
  `use_configured_oauth_user` 布尔开关。
- OpenAPI 只有配置 `--api-key` 或 `ZHIHU_OPENWEBUI_API_KEY` 时才启用
  Bearer 鉴权；无 key 模式只能用于本机或受控私网。
- 不提供任意 URL 或原始 HTTP 透传工具。
- 官方额度接口是唯一免费额度来源；本地保护只计发送预留次数，不预测钱包余额，不是账单。


## 调用与费用保护（2026-10-13）

默认是免费保护模式：每个业务请求先即时查询对应的官方免费额度；查询失败、缺少有效额度、额度不足或映射未确认时，不发送业务请求。额度查询本身不递归预查、不消耗本地上限。工具名及业务路径保持原样；旧额度输入 `question_answers` 映射为 `question_discovery`，问题推荐和回答摘要共用该组。

本地北京时间每日上限默认 **100 次**，可设为 1–100000。计数口径是已持久化预留的业务请求：包括已发送后失败、取消或结果未知的请求；预查失败不占用上限。它与官方免费次数、已有本地工具使用统计、钱包和账单分别处理，不估算费用或余额。

免费模式可使用有可靠额度映射的 fast/thinking 直答、问题推荐以及 PDF/PPT 任务；缺少单价不影响使用已确认的免费额度。显式付费模式对未确认计费的能力保守拒绝，并提示切换回免费保护模式。通用资源文件上传尚无可靠额度映射，暂时阻止；知识库上传的 `knowledge` 映射已确认。

两个客户端共用 `~/.config/zhihu-search/call-policy/daily.json` 和 `request.lock`；`ZHIHU_SEARCH_HOME` 可改变根目录，`ZHIHU_CALL_POLICY_DIR` 可显式指定共同保护目录。同目录内所有账号/进程共用一个本地上限，避免多 Secret 或多入口绕开计数；自定义目录时需让两项目使用同一路径。锁覆盖预查与请求，状态先原子预留，不缓存额度、不自动重试。网络失败或取消后的未知请求保守占用对应免费容量，跨日仍保留这些未知预留。

本地保护**不能承诺绝对零费用**：同账号其他客户端可能在预查后竞争免费额度，平台扣费时间也不由本机控制。结果未知时先在官方控制台核对，不盲目重试。进程崩溃留下的锁不会自动抢占；确认两个客户端均无在途请求、核对未知请求后才可手动移除 `request.lock`。损坏的计数文件会失败关闭，不自动清零。

鉴权和账号设置保持不变。不提供充值、权益兑换或钱包查询。官方依据：[服务价格](https://developer.zhihu.com/docs?key=billing_price)、[免费额度](https://developer.zhihu.com/docs?key=quota)、[线上订购协议](https://developer.zhihu.com/content/order-agreement)（V1.0，2026-10-10 生效）。API 计费不扩大内容访问或传播授权范围。

官方额度更新也可能滞后：免费模式每次仍查询官方值，同时保留本机已消耗预留的容量上限，取更保守的值，不在当天自动补回；这个内部上限不会作为官方余额展示。次日按北京时间重置，结果未知的预留仍保留。
