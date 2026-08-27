# zhihu-search

让 Agent 按需查找知乎与中文社区信息，也可以直接调用知乎开放平台的搜索、
直答、热榜、额度、用户公开数据、知识库、PDF、PPT 和 OAuth 辅助能力。

## 从 Skill 开始

对大多数人来说，**安装 Skill 就够了**。它会在需要中文社区观点、真实体验、
口碑、避坑信息或国内热点时主动选择合适的查询方式；平时不会启动常驻服务。

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
uvx zhihu-search --probe
```

不要把 Access Secret 发到聊天、截图或仓库。`--probe` 会真实请求一次知乎
热榜，因此会消耗一次请求额度。

### 3. 直接告诉 Agent 你想查什么

例如：

> 帮我查一下最近主流的 RAG 评测方法在中文开发者社区的讨论，返回 3 条并附来源链接。

Skill 会按任务选择搜索、直答或热榜。默认按需执行一条最窄的 CLI 命令；如果
当前客户端已经提供匹配的 `zhihu` MCP 工具，它会直接复用，不会重复查询。

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
| `office` | compact 加 2 个 PDF 和 2 个 PPT 工具 |
| `full` | 16 个业务/账号工具加 `other`，共 17 个 |

档位和工具名可以用逗号组合，例如 `knowledge,user` 或
`compact,knowledge_search`。只写工具名时是严格 allowlist，例如
`search,ask,pdf_status`。`ZHIHU_MCP_TOOLS` 可以设置默认值，命令行
`--tools` 的优先级更高。

`other` 的 `enable`、`disable`、`reset` 只影响当前 MCP 会话。使用档位时，
它能管理全部 13 个低频工具；使用纯工具名 allowlist 时，它不能越过启动时的
允许范围。

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
```

低频能力同样可以直接调用：

```bash
uvx zhihu-search user-contents --content-type article --limit 10
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

### DeepSeek Harness

DSH 用户通过原生 bundle 安装**同一份 Skill**，不需要再注册 MCP：

```bash
dsh plugin --profile web add "github:klarkxy/zhihu-search"
```

bundle 不保存知乎凭证，也不会启动常驻 MCP。安装、验证、固定版本和移除步骤
见 [DSH 指南](setup/dsh.md)。

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
| 官方额度 | 1 | 总额度、已用额度和剩余额度 |
| 用户公开数据 | 5 | 创作、关注、近期收藏和收藏夹 |
| 知识库 | 4 | 列表、内容、上传、检索 |
| PDF 解析 | 3 | 上传、创建任务、查询状态 |
| PPT 生成 | 2 | 创建任务、查询状态 |
| OAuth 辅助 | 2 | 授权 URL、授权码换 token |

逐端点说明、官方文档差异和安全边界见
[API 覆盖与边界](docs/API_COVERAGE.md)。

## 凭证与排障

Access Secret 的读取顺序是：

1. `ZHIHU_ACCESS_SECRET`；
2. `~/.config/zhihu-search/credentials.json`。

常用诊断命令：

```bash
uvx zhihu-search --check-token
uvx zhihu-search --probe
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

额度现在完全以知乎官方 `GET /api/v1/quota` 为准。本地计数、熔断、
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
