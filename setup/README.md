# 安装与配置

按使用频率选择入口：

| 顺序 | 方式 | 适合场景 |
|---:|---|---|
| 1 | DSH 插件 | DeepSeek Harness；把同一份 Skill 装进 profile |
| 2 | Skill | 其他 Agent；主动识别任务，按需 CLI，已有 MCP 才复用 |
| 3 | CLI | 临时调用或脚本 |
| 4 | MCP | AI 客户端高频使用 |
| 5 | OpenWebUI | 需要 HTTP 工具服务器 |

## 通用准备

Skill、CLI 和 MCP 都通过 [uv](https://docs.astral.sh/uv/) 的 `uvx` 运行：

```bash
uvx --version
```

找不到命令时，先按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)
安装并重新打开终端。

在 [知乎开放平台个人中心](https://developer.zhihu.com/personal) 创建 Access
Secret，然后只在自己的终端执行：

```bash
uvx zhihu-search --save-token "<你的 Access Secret>"
uvx zhihu-search --probe
```

不要把 Access Secret、OAuth `app_key` 或 OAuth token 发到聊天中，也不要
写进配置、截图或仓库。

## 1. 安装 DSH 插件

DeepSeek Harness 用户直接把 bundle 安装进目标 profile：

```bash
dsh plugin --profile web add "github:klarkxy/zhihu-search"
```

插件不保存密钥，也不启动 MCP。它只把同一份 Skill 挂进 profile，查询仍走
按需 `uvx zhihu-search`。完整安装、验证与移除步骤见 [dsh.md](dsh.md)。

## 2. 安装 Skill（推荐）

```bash
uvx zhihu-search install-skill
```

该命令调用 `npx skills`，默认全局安装给 Codex，并以
`~/.agents/skills` 为统一来源。只有用户明确需要隔离时才加 `--project`，
安装到当前项目的 `.agents/skills`；其他客户端可使用 `--agent <名称>`。
安装后重新打开 Codex 任务。Skill 会根据任务选择 `search`、`ask` 或
`trending`；如果已经注册 `zhihu` MCP 则优先调用 MCP，否则回退对应的
`uvx zhihu-search` 命令。

## 3. 直接使用 CLI

```bash
uvx zhihu-search search "RAG 评测方法" --count 5
uvx zhihu-search --help
```

在仓库目录验证尚未发布的代码时，使用
`uvx --from . zhihu-search <command>`。

## 4. MCP（高频集成）

推荐显式启用 compact 模式：

```bash
uvx zhihu-search serve --tools compact
```

compact 只暴露 `search`、`ask`、`trending` 和 `other`。`other` 可在当前
会话中通过 `enable`、`disable`、`reset` 展开、收起或复原 12 个低频工具。

除 `compact` 和 `full` 外，还有 `knowledge`、`user`、`office` 三个档位，
各自在 compact 基础上常驻一组能力。档位名与工具名可以逗号混写取并集，
例如 `--tools knowledge,user` 或 `--tools compact,knowledge_search`。
建有知乎知识库、希望私有文档检索始终可见的用户，推荐 `--tools knowledge`，
否则模型看不到该工具时会静默退回全网搜索。

只写工具名（如 `search,ask,pdf_status`）则是严格 allowlist，其中的 `other`
只能管理已经列入 allowlist 的低频工具，不能展开被排除的工具。

`ZHIHU_MCP_TOOLS` 可设置默认工具配置，命令行 `--tools` 优先。

| 客户端 | 配置指南 |
|---|---|
| Claude Code | [claude-code.md](claude-code.md) |
| Codex | [codex.md](codex.md) |
| OpenCode | [opencode.md](opencode.md) |
| HanaAgent / OpenHanako | [hanako-agent.md](hanako-agent.md) |
| DeepSeek Harness | [dsh.md](dsh.md) |

MCP 会读取本机保存的凭证，不需要在客户端配置中添加密钥。
注册后，Skill 会优先使用 MCP 的三个核心工具。

## 5. OpenWebUI（少数场景）

需要 HTTP OpenAPI 工具服务器时运行：

```bash
uvx zhihu-search openwebui \
  --host 0.0.0.0 --port 8000 --api-key "<服务访问口令>"
```

## 维护与排障

```bash
uvx zhihu-search --check-token
uvx zhihu-search --probe
uvx zhihu-search --quota
uvx zhihu-search --clear-token
```

`--check-token` 只报告是否已配置及凭证来源，不输出 Secret 片段或本机凭证
路径。`--probe` 会真实调用一次 `hot_list(limit=1)` 并消耗一次请求额度。

| 症状 | 处理 |
|---|---|
| 找不到 `uvx` | 安装 uv，并重新打开终端 |
| 凭证无效 | 重新创建 Access Secret，再执行 `--save-token` |
| 知乎上游暂不可达 | 稍后重新执行 `--probe` |
| MCP 工具不符合预期 | 检查 `--tools`、`ZHIHU_MCP_TOOLS` 并重启客户端 |
| 返回 `Code=30002` | 到知乎开放平台检查账号额度或接口权限 |
