# Agent 安装与验证指南

默认全局安装 `zhihu-search` Skill。CLI 适合临时调用；只有用户明确表示会
高频使用时才配置 MCP；MCP 已存在时 Skill 必须优先调用核心 MCP 工具，CLI
只作回退。OpenWebUI 放在最后考虑。

完成标准：目标入口真实调用成功，且所有密钥都没有进入聊天、日志或客户端
配置。

## 安全规则

- 不要让用户在聊天中粘贴任何密钥。
- Access Secret 只保存在本机凭证文件或进程环境中。
- `ZHIHU_OAUTH_TOKEN` 只放在服务端；模型只接收
  `use_configured_oauth_user` 布尔开关。
- `pdf-upload`、`knowledge-upload`、`oauth-url` 和 `oauth-token` 只允许从 CLI/Python 调用。
- MCP 不接收本机文件路径、OAuth `app_key` 或 OAuth token。

## 1. 准备 uvx 和凭证

```bash
uvx --version
uvx zhihu-search --version
uvx zhihu-search --check-token
```

找不到 `uvx` 时先安装 [uv](https://docs.astral.sh/uv/)。凭证缺失时，让
用户打开 [知乎开放平台个人中心](https://developer.zhihu.com/personal)
创建 Access Secret，并只在自己的终端保存：

```bash
uvx zhihu-search --save-token "<Access Secret>"
uvx zhihu-search --probe
```

`--check-token` 只证明凭证可读取，并且只输出配置状态和来源，不输出 Secret
片段或凭证文件路径。必须以 `--probe` 的真实上游响应作为连通性判断；该命令
会调用一次 `hot_list(limit=1)` 并消耗一次请求额度。

## 2. 优先安装 Skill

```bash
uvx zhihu-search install-skill
```

这是 Codex 的跨仓库默认，内部调用 `npx skills`，以
`~/.agents/skills` 为统一来源。其他客户端使用
`--agent <名称>`；只有用户明确要求项目隔离时才加 `--project`。底层等价
命令是：

```bash
npx skills add klarkxy/zhihu-search --skill zhihu-search -g -a codex -y
```

让目标 Agent 重新加载 Skill，然后真实执行一次查询：

> 帮我查一下最近主流的 RAG 评测方法，返回 2 条并附来源链接。

Skill 能在未点名知乎时被发现、查询成功且返回链接，即完成默认安装。不要为
单次任务继续安装 MCP；如果 MCP 已存在，确认 Skill 使用 MCP 而不是重复运行
CLI。

## DeepSeek Harness 使用原生插件

目标客户端是 DSH 时，不修改 Python CLI，也不手写 profile patch；安装正式
bundle：

```bash
dsh plugin --profile web add "github:klarkxy/zhihu-search"
dsh --profile web --dump-config
```

配置 dump 必须包含 `zhihu-search-skill` 和
`@deepseek-ai/dsh-skill-filesystem`。持久安装后停止并重启目标 profile，再
确认 Skill 目录出现 `zhihu-search`，并由 Agent 按需执行
`uvx zhihu-search` 完成真实查询。不要为了这个 bundle 再注册常驻 MCP。
插件配置中不得写入任何知乎凭证。完整流程见 [setup/dsh.md](setup/dsh.md)。

## 3. CLI 作为直接入口

不支持 Skill，或用户需要脚本调用时，直接使用：

```bash
uvx zhihu-search search "RAG 评测方法" --count 2
```

完整命令以 `uvx zhihu-search --help` 为准。

## 4. 高频使用时配置 MCP

先确认目标客户端，再读取对应指南：

| 客户端 | 指南 |
|---|---|
| Claude Code | [setup/claude-code.md](setup/claude-code.md) |
| Codex | [setup/codex.md](setup/codex.md) |
| HanaAgent | [setup/hanako-agent.md](setup/hanako-agent.md) |
| OpenCode | [setup/opencode.md](setup/opencode.md) |
| 其他 | [setup/README.md](setup/README.md) |

默认配置核心：

```text
command: uvx
args:    zhihu-search serve --tools compact
```

| 工具配置 | 行为 |
|---|---|
| `compact` | 暴露 `search`、`ask`、`trending`、`other` |
| `knowledge` | compact 加 3 个知识库工具 |
| `user` | compact 加 5 个用户数据工具 |
| `office` | compact 加 2 个 PDF 和 2 个 PPT 工具 |
| `full` | 暴露全部 17 个工具 |
| 逗号混写 | 档位名与工具名取并集，如 `knowledge,user` |
| 纯工具名 allowlist | 严格只允许指定工具 |

`other` 的 `enable`、`disable`、`reset` 只改变当前 MCP 会话，可展开、收起
或复原低频显式工具。选择里含档位名时可管理全部 13 个；纯工具名 allowlist
只能管理其中已允许的工具，不能越过启动开关。`ZHIHU_MCP_TOOLS`
可设置默认值，但命令行 `--tools` 优先。

写入配置时：

1. 保留所有已有 MCP server，只新增或更新 `zhihu`。
2. 不写入任何知乎凭证。
3. 写前、写后都解析 JSON 或 TOML。
4. 在写入配置的同一目标用户上下文中运行 `codex mcp get zhihu`，确认
   `enabled: true`、`command: uvx`，且参数包含
   `zhihu-search serve --tools compact`；不要只把 `Added global MCP server`
   的提示当作成功证据。
5. 让用户新建或重新打开 Codex 任务；新任务仍未出现工具时再重启客户端。
6. 用未点名知乎的资料查询验证一次真实 `search`。

compact 启动时应看到 4 个工具；knowledge 7 个，office 8 个，user 9 个，
full 17 个。不要擅自结束用户的客户端进程。

## 5. 最后才考虑 OpenWebUI

只有用户明确需要 HTTP OpenAPI 工具服务器时，才运行：

```bash
uvx zhihu-search openwebui \
  --host 0.0.0.0 --port 8000 --api-key "<服务访问口令>"
```

无访问口令时只能监听 localhost 或受控私网。一般 Agent 使用不需要这一层。

## 排障与清理

| 症状 | 处理 |
|---|---|
| 找不到 `uvx` | 安装 uv 并重新打开终端 |
| `--probe` 失败 | 检查凭证和网络，不要循环请求 |
| MCP 工具数不对 | 检查 `--tools`、`ZHIHU_MCP_TOOLS` 后重启客户端 |
| `Code=30002` | 运行 `--quota` 查看官方剩余额度，再检查接口权限 |
| OAuth 用户调用失败 | 在服务端配置 `ZHIHU_OAUTH_TOKEN` |
| PDF/PPT 长期处理中 | 稍后查询状态，不要紧密轮询 |

移除本机凭证：

```bash
uvx zhihu-search --clear-token
```

`uvx` 是按需运行，不需要卸载 Python 包。
