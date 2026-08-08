# 安装与配置

按使用频率选择入口：

| 顺序 | 方式 | 适合场景 |
|---:|---|---|
| 1 | Skill | 推荐；主动识别任务，优先 MCP、回退 CLI |
| 2 | CLI | 临时调用或脚本 |
| 3 | MCP | AI 客户端高频使用 |
| 4 | OpenWebUI | 需要 HTTP 工具服务器 |

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

## 1. 安装 Skill（推荐）

```bash
npx skills add klarkxy/zhihu-search --skill zhihu-search -g -a codex -y
```

`-g` 是跨仓库默认；只有用户明确需要隔离时才去掉 `-g`，安装到当前项目。
安装后重新打开 Codex 任务。Skill 会根据任务选择 `search`、`ask` 或
`trending`；如果已经注册 `zhihu` MCP 则优先调用 MCP，否则回退对应的
`uvx zhihu-search` 命令。

## 2. 直接使用 CLI

```bash
uvx zhihu-search search "RAG 评测方法" --count 5
uvx zhihu-search --help
```

在仓库目录验证尚未发布的代码时，使用
`uvx --from . zhihu-search <command>`。

## 3. 配置 MCP（高频使用）

推荐显式启用 compact 模式：

```bash
uvx zhihu-search serve --tools compact
```

compact 只暴露 `search`、`ask`、`trending` 和 `other`。`other` 可在当前
会话中通过 `enable`、`disable`、`reset` 展开、收起或复原 9 个低频工具。
如需一次暴露全部 13 个工具，使用 `--tools full`；也可传入
`search,ask,pdf_status` 这类严格逗号 allowlist。自定义列表中的 `other`
只能管理已经列入 allowlist 的低频工具，不能展开被排除的工具。

`ZHIHU_MCP_TOOLS` 可设置默认工具配置，命令行 `--tools` 优先。

| 客户端 | 配置指南 |
|---|---|
| Claude Code | [claude-code.md](claude-code.md) |
| Codex | [codex.md](codex.md) |
| OpenCode | [opencode.md](opencode.md) |
| HanaAgent / OpenHanako | [hanako-agent.md](hanako-agent.md) |

MCP 会读取本机保存的凭证，不需要在客户端配置中添加密钥。
注册后，Skill 会优先使用 MCP 的三个核心工具。

## 4. OpenWebUI（少数场景）

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

| 症状 | 处理 |
|---|---|
| 找不到 `uvx` | 安装 uv，并重新打开终端 |
| 凭证无效 | 重新创建 Access Secret，再执行 `--save-token` |
| 知乎上游暂不可达 | 稍后重新执行 `--probe` |
| MCP 工具不符合预期 | 检查 `--tools`、`ZHIHU_MCP_TOOLS` 并重启客户端 |
| 返回 `Code=30002` | 到知乎开放平台检查账号额度或接口权限 |
