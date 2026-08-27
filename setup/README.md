# 安装与配置

这页只回答一个问题：**我该选哪种接入方式？**

| 优先级 | 方式 | 什么时候用 |
|---:|---|---|
| 1 | **Skill** | 默认选择；DSH 通过专用 bundle 安装同一份 Skill |
| 2 | **MCP** | 同一客户端里需要持续、高频调用 |
| 3 | CLI | 临时查询、脚本和调试 |
| 4 | OpenWebUI | 明确需要 HTTP 工具服务器 |

不确定时就选 Skill。几种方式不是“全家桶”，无需全部安装。

## 准备 uvx、npx 和凭证

Skill、CLI 和 MCP 都通过 [uv](https://docs.astral.sh/uv/) 的 `uvx` 按需运行：

```bash
uvx --version
npx --version
```

找不到 `uvx` 时，按 [uv 官方说明](https://docs.astral.sh/uv/getting-started/installation/)
安装；找不到 `npx` 时，安装 [Node.js](https://nodejs.org/)。完成后重新打开终端。

在[知乎开放平台个人中心](https://developer.zhihu.com/personal)创建 Access
Secret，并只在自己的终端保存：

```bash
uvx zhihu-search --save-token "<你的 Access Secret>"
uvx zhihu-search --probe
```

不要把 Access Secret、OAuth `app_key` 或 OAuth token 发到聊天中，也不要
写进客户端配置、截图或仓库。

## 1. Skill（默认选择）

```bash
uvx zhihu-search install-skill
```

这条命令通过 `npx skills` 为 Codex 做用户级安装。只有明确需要项目隔离时才
加 `--project`；安装给其他 Agent 时使用 `--agent <名称>`：

```bash
uvx zhihu-search install-skill --agent codex --agent claude-code
uvx zhihu-search install-skill --project
```

安装后新建一个 Agent 任务，再发送一条不生硬点名工具的测试请求：

> 帮我查一下最近主流的 RAG 评测方法在中文开发者社区的讨论，返回 3 条并附来源链接。

Skill 默认按需执行一条最窄的 CLI 命令；当前会话已经有匹配的知乎 MCP 工具
时才直接复用。**不要为了偶尔查询额外注册 MCP。**

Codex 的加载和验证细节见 [Codex 配置](codex.md)。

### DSH 用户：通过 bundle 安装同一份 Skill

DeepSeek Harness 不运行通用 `install-skill`，而是使用原生 bundle：

```bash
dsh plugin --profile web add "github:klarkxy/zhihu-search"
```

bundle 不保存密钥，也不启动 MCP；查询仍按需执行 `uvx zhihu-search`。完整
流程见 [DSH 指南](dsh.md)。

## 2. MCP（高频集成）

只有高频、持续使用，并接受客户端进程生命周期时才配置 MCP。服务端入口是：

```bash
uvx zhihu-search serve --tools compact
```

| 档位 | 常驻工具 |
|---|---|
| `compact` | `search`、`ask`、`trending`、`other` |
| `knowledge` | compact 加 3 个知识库工具 |
| `user` | compact 加 5 个用户数据工具 |
| `office` | compact 加 4 个 PDF/PPT 工具 |
| `full` | 16 个业务/账号工具加 `other`，共 17 个 |

`other` 可以在当前会话中展开、收起或复原 13 个低频工具。档位和工具名可用
逗号组合，例如 `knowledge,user` 或 `compact,knowledge_search`；只写工具名
时则是严格 allowlist。`ZHIHU_MCP_TOOLS` 可设置默认值，命令行 `--tools`
优先。

建有知乎知识库、需要私有文档检索始终可见时选 `knowledge`，否则模型可能因
看不到知识库工具而退回普通搜索。

选择你的客户端：

| 客户端 | 配置指南 |
|---|---|
| Codex | [codex.md](codex.md) |
| Claude Code | [claude-code.md](claude-code.md) |
| OpenCode | [opencode.md](opencode.md) |
| HanaAgent / OpenHanako | [hanako-agent.md](hanako-agent.md) |

MCP 读取本机凭证，不要把任何知乎密钥写入客户端配置。配置完成后，Skill 会
复用可见的匹配工具，避免重复查询。

## 3. 直接使用 CLI

适合临时查询、自动化脚本和排障：

```bash
uvx zhihu-search search "RAG 评测方法" --count 5
uvx zhihu-search --help
```

在仓库目录验证尚未发布的代码时，使用
`uvx --from . zhihu-search <command>`。

## 4. OpenWebUI

只有需要 HTTP OpenAPI 工具服务器时才运行：

```bash
uvx zhihu-search openwebui \
  --host 0.0.0.0 --port 8000 --api-key "<服务访问口令>"
```

没有访问口令时，只能在 localhost 或受控私网中使用。

## 维护与排障

```bash
uvx zhihu-search --check-token
uvx zhihu-search --probe
uvx zhihu-search --quota
uvx zhihu-search --clear-token
```

`--check-token` 不发起上游请求，只报告凭证状态和来源；`--probe` 会真实调用
一次 `hot_list(limit=1)`；`--quota` 查询知乎官方额度，不使用本地计数。

| 现象 | 建议处理 |
|---|---|
| 找不到 `uvx` | 安装 uv 后重开终端 |
| 凭证无效 | 重新创建 Access Secret，再执行 `--save-token` |
| 知乎上游暂不可达 | 稍后再执行一次 `--probe`，不要循环请求 |
| MCP 工具不符合预期 | 检查 `--tools` 和 `ZHIHU_MCP_TOOLS`，再重启客户端 |
| 返回 `Code=30002` | 用 `--quota` 查看剩余额度，再检查接口权限 |
