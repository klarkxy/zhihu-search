# zhihu-search

让 Agent 按需查找知乎与中文社区信息，也可以直接调用知乎开放平台的搜索、
直答、热榜、额度、本人公开数据、问题发现、创作能力、知识库、PDF、PPT 和
OAuth 辅助能力。

## 从 Skill 开始

对大多数人来说，**安装 Skill 就够了**。它会在需要中文社区观点、真实体验、
口碑、避坑信息或国内热点时选择合适的查询方式，不会仅因为问题是中文就触发；
平时不会启动常驻服务。

### 1. 安装 Skill

这一步需要 `uvx` 和 `npx`。如果还没有，请先安装
[uv](https://docs.astral.sh/uv/getting-started/installation/) 和
[Node.js](https://nodejs.org/)；安装后重新打开终端。

```bash
uvx zhihu-search install-skill
```

默认会通过官方 `npx skills` 全局安装给 Codex。安装完成后，新建一个 Codex
任务，让客户端重新加载 Skill。

### 2. 保存知乎 Access Secret

在[知乎开放平台个人中心](https://developer.zhihu.com/personal)创建 Access
Secret，然后只在自己的终端执行：

```bash
uvx zhihu-search --save-token "<你的 Access Secret>"
uvx zhihu-search --check-token
```

不要把 Access Secret 发到聊天、截图或仓库。`--check-token` 不发请求；想确认
端到端连通时，可以选做一次 `uvx zhihu-search --probe`，它会真实请求一次知乎
热榜并消耗一次 `hot_list` 额度，不要循环执行。

### 3. 直接告诉 Agent 你想查什么

例如：

> 帮我查一下最近主流的 RAG 评测方法在中文开发者社区的讨论，返回 3 条并附来源链接。

Skill 会按所需证据选择搜索、直答或热榜：先查一次，证据够就直接回答，只有
关键缺口时才定向补查。如果当前客户端已经提供匹配的 `zhihu` MCP 工具，它会
直接复用，不会再走 CLI 重复查询。

需要安装到其他 Agent，或只安装到当前项目时：

```bash
uvx zhihu-search install-skill --agent codex --agent claude-code
uvx zhihu-search install-skill --project
```

完整的安装范围和验收方法见[安装与配置](setup/README.md)；由 Agent 代为配置
时，请看 [Agent 安装与验证指南](AGENT_SETUP.md)。

## 高频使用时再配置 MCP

如果你会在同一个 AI 客户端里持续、高频调用知乎能力，可以把 MCP 作为第二
选择。偶尔查询不需要配置它：Skill 本身不依赖 MCP，而且常驻 stdio 服务会
跟随客户端的进程生命周期。

通用启动配置：

```text
command: uvx
args:    zhihu-search serve --tools compact
```

`compact` 默认只展示三个核心工具和一个会话内开关：

- `search`：知乎或全网搜索；
- `ask`：知乎直答；
- `trending`：知乎热榜；
- `other`：在当前会话内展开、收起或复原低频工具。

按长期需要选择档位：

| 档位 | 常驻可见的能力 |
|---|---|
| `compact`（默认） | `search`、`ask`、`trending`、`other` |
| `knowledge` | compact 加 3 个知识库工具 |
| `user` | compact 加 5 个用户数据工具 |
| `questions` | compact 加问题推荐和问题回答摘要 |
| `creator` | compact 加全文、评论和 2 个创作统计工具 |
| `office` | compact 加 2 个 PDF 和 2 个 PPT 工具 |
| `sync` | compact 加 7 个同步工具：保存/读取草稿、校验、预览、确认后发布、上传图片 |
| `full` | 22 个上游业务/账号工具、2 个本地研究工具，加 `other`，共 25 个。不含 `sync` |

档位和工具名可以用逗号组合，例如 `knowledge,user` 或
`compact,knowledge_search`。只写工具名时是严格 allowlist，例如
`search,ask,pdf_status`。`ZHIHU_MCP_TOOLS` 可以设置默认值，命令行
`--tools` 的优先级更高。

`other` 的 `enable`、`disable`、`reset` 只影响当前 MCP 会话。使用档位时，
它能管理全部 21 个低频工具；使用纯工具名 allowlist 时，它不能越过启动时的
允许范围。`sync` 不在这 21 个里面，`other` 不会把它展开。

客户端配置：

- [Codex](setup/codex.md)
- [Claude Code](setup/claude-code.md)
- [OpenCode](setup/opencode.md)
- [HanaAgent / OpenHanako](setup/hanako-agent.md)

PDF/知识库本机上传和 OAuth token 交换不会暴露为模型可调用工具，只能从
CLI 或 Python 执行。

## 其他入口

这些方式解决的是特定需求，不需要和 Skill 一起全部安装。

### 直接使用 CLI

适合临时查询、脚本和调试：

```bash
uvx zhihu-search search "RAG 评测方法" --count 5
uvx zhihu-search ask "什么是 ReAct Agent？" --model thinking
uvx zhihu-search trending --limit 10
uvx zhihu-search quota --api-id knowledge
uvx zhihu-search research recent "减肥药近期进展" --window-days 30 --format json
uvx zhihu-search research-render evidence.json synthesis.json --out ./research-out
```

低频能力同样可以直接调用：

```bash
uvx zhihu-search user-contents --content-type article --limit 10
uvx zhihu-search question-recommendations --query "AI Agent" --count 5
uvx zhihu-search question-answers "https://www.zhihu.com/question/123"
uvx zhihu-search user-content-detail "https://zhuanlan.zhihu.com/p/123"
uvx zhihu-search creator-account-stats --content-type all
uvx zhihu-search knowledge-search "退款规则" --recall-scope personal
uvx zhihu-search pdf-upload "./report.pdf"
uvx zhihu-search ppt-create "https://zhuanlan.zhihu.com/p/123" --pages 12
```

所有业务命令都支持 `--format json`。完整参数以帮助信息为准：

```bash
uvx zhihu-search --help
uvx zhihu-search <command> --help
```

在仓库内验证尚未发布的代码时，把命令开头改为
`uvx --from . zhihu-search`。

### 同步到知乎

把已有文章、提问或想法适配成知乎格式、本地预览，并在你明确确认后发布。
这组凭证与搜索 Access Secret 不是同一项，在
[知乎同步助手申请页](https://www.zhihu.com/playground/zhihu-sync)获取：

```bash
uvx zhihu-search --save-openapi "<授权说明全文>"
uvx zhihu-search --check-openapi
uvx zhihu-search sync-prepare --type article --title "创造力，从何而来？" --body-file ./draft.md
uvx zhihu-search sync-preview <draft-id>
uvx zhihu-search sync-publish <draft-id> --confirm --preview-token <token>
```

`--save-openapi` 接受知乎给出的整段授权说明，其中要写成
`ZHIHU_OPENAPI_APP_KEY:"…"` 和 `ZHIHU_OPENAPI_APP_SECRET:"…"`。
`--check-openapi` 只报告来源和 App Key，不显示 App Secret。
没有预览、也没有你的明确确认时，发布命令不会请求知乎。视频不支持。
高频 MCP 需要单独选择 `sync` 档位。OpenWebUI 不提供发布。

### DeepSeek Harness

DSH 插件已迁到
[`plugins/dsh-zhihu`](https://github.com/klarkxy/dsh-plugins/tree/main/plugins/dsh-zhihu)，
本仓库不再维护它：

```bash
dsh plugin --profile web add @klarkxy/dsh-zhihu
```

安装和从旧安装包切换的步骤见 [DSH 指南](setup/dsh.md)。

### OpenWebUI

只有明确需要 HTTP OpenAPI 工具服务器时才使用：

```bash
uvx zhihu-search openwebui \
  --host 0.0.0.0 --port 8000 --api-key "<服务访问口令>"
```

在 Open WebUI 中添加 External Tool Server，地址填
`http://<server>:8000`，认证方式选择 Bearer token。未配置访问口令时，
服务只能用于 localhost 或受控私网。

## 能做什么

| 能力 | 端点数 | 说明 |
|---|---:|---|
| 搜索、直答、热榜 | 4 | 知乎搜索、全网搜索、直答、热榜 |
| 问题发现 | 2 | 适合回答的问题，以及问题下的回答摘要 |
| 官方额度 | 1 | 总额度、已用额度和剩余额度 |
| 本人公开数据 | 5 | 创作、关注、近期收藏和收藏夹 |
| 创作能力 | 4 | 本人全文、评论、账号统计和单篇统计 |
| 知识库 | 4 | 列表、内容、上传、检索 |
| PDF 解析 | 3 | 上传、创建任务、查询状态 |
| PPT 生成 | 2 | 创建任务、查询状态 |
| OAuth 辅助 | 2 | 授权 URL、授权码换 token |
| 研究检索与本地报告 | 0 | 组合已有搜索；校验宿主结果后写本地 Markdown、JSON 和单文件 HTML |

研究不是新的知乎接口。`research` 只返回带引用、时间和预算的证据包；
`research-render` 校验宿主写出的结构，再生成本地文件。数字要能在摘录里找到，
或标明假设。不确定日期不会写进确认时间线。结果不会发布。细节见
[API 覆盖与边界](docs/API_COVERAGE.md)。

逐端点说明、官方文档差异和安全边界见
[API 覆盖与边界](docs/API_COVERAGE.md)。

## 调用与费用保护

默认是免费保护模式：业务请求会按对应的知乎官方免费额度分组预查；额度充足（剩余不少于 20）时，同一分组最多每 5 分钟重新查询一次，额度接近耗尽或无法确认时则每次请求前查询。预查失败、缺少有效额度、额度不足或映射未确认时，不发送业务请求。额度查询本身不递归预查。

本地北京时间每日上限默认 **1000 次**，可设为 1–100000；计数包含已发送后失败、取消或结果未知的请求。进程内会短时间复用相同的搜索、全网搜索、热榜和问题回答结果（约 5–10 分钟），命中复用结果不再消耗额度。两个客户端共用保护状态；同目录内所有账号/进程共用一个本地上限。

显式付费模式可用环境变量 `ZHIHU_ALLOW_PAID=true` 开启；`ZHIHU_DAILY_CALL_LIMIT` 调整每日上限。CLI 也可以传 `--allow-paid` 和 `--daily-call-limit`（放在子命令前），MCP/OpenAPI 通过启动环境配置。未确认计费规则的能力即使开启付费模式也会保守拒绝。

保护锁只覆盖本地账本的预留与结算，业务请求可以并发执行；进程崩溃留下的锁约 60 秒后会自动恢复。网络失败或取消后的结果未知请求保守占用对应免费容量；北京时间跨日后本地计数和预留重置。

本地保护**不能承诺绝对零费用**：同账号其他客户端可能在预查后竞争免费额度，平台扣费时间也不由本机控制。结果未知时先在官方控制台核对，不盲目重试。官方依据：[服务价格](https://developer.zhihu.com/docs?key=billing_price)、[免费额度](https://developer.zhihu.com/docs?key=quota)、[线上订购协议](https://developer.zhihu.com/content/order-agreement)。API 计费不扩大内容访问或传播授权范围。

## 凭证与排障

Access Secret 的读取顺序是：

1. `ZHIHU_ACCESS_SECRET`；
2. `~/.config/zhihu-search/credentials.json`。

常用诊断命令：

```bash
uvx zhihu-search --check-token
uvx zhihu-search --probe        # 可选，消耗一次 hot_list 额度
uvx zhihu-search --quota
uvx zhihu-search --clear-token
```

`--check-token` 只显示配置状态和来源，不会输出 Secret 片段或本机凭证路径；
`--quota` 查询知乎官方额度，不读取本地计数，也不消耗业务额度。

| 现象 | 建议处理 |
|---|---|
| 找不到 `uvx` | 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/) 后重开终端 |
| 凭证不存在或失效 | 在个人中心重新创建并保存 Access Secret |
| 返回 `Code=30002` | 用 `--quota` 查看官方剩余额度，再检查接口权限 |
| MCP 工具没有出现 | 检查配置并重启对应客户端 |
| PDF/PPT 长时间处理中 | 稍后再查状态，不要紧密轮询 |
| 知识库列表为空 | 先登录[直答知识库](https://zhida.zhihu.com/repositories/square)完成初始化 |

## 2.0 迁移说明

官方剩余额度以 `GET /api/v1/quota` 为准。旧的本地余额预测、
`--reset-quota` 以及各类响应中的本地 `quota` 字段已经移除。旧的本机
`quota.json` 不会被删除，但也不会再读取。

## 开发

```bash
git clone https://github.com/klarkxy/zhihu-search
cd zhihu-search
uv sync --extra dev
uv run pytest
uv build
```

## 许可证

[SATA License v2.0](LICENSE)
