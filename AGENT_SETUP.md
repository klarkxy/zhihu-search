# Agent 安装与验证指南

这份指南给“代用户安装和验收”的 Agent 使用。默认目标是一个简单的闭环：

1. 安装 Skill；
2. 让用户在自己的终端保存凭证；
3. 用一条真实请求确认 Skill 能被发现并返回来源。

只有用户明确需要高频、常驻集成时才继续配置 MCP。CLI、DSH 和 OpenWebUI
都是特定场景入口，放在后面处理。

## 先守住安全边界

- 不要让用户在聊天中粘贴任何密钥。
- Access Secret 只保存在本机凭证文件或进程环境中。
- `ZHIHU_OAUTH_TOKEN` 只放在服务端；模型只接收
  `use_configured_oauth_user` 布尔开关。
- `pdf-upload`、`knowledge-upload`、`oauth-url`、`oauth-token` 只允许从
  CLI/Python 调用。
- MCP 不接收本机文件路径、OAuth `app_key` 或 OAuth token。

完成标准不是“命令退出码为 0”，而是目标入口真实调用成功，并且密钥没有
进入聊天、日志或客户端配置。

## 1. 安装并验证 Skill

先确认 `uvx`、`npx` 和凭证状态：

```bash
uvx --version
npx --version
uvx zhihu-search --version
uvx zhihu-search --check-token
```

找不到 `uvx` 时，引导用户安装 [uv](https://docs.astral.sh/uv/)；找不到 `npx`
时安装 [Node.js](https://nodejs.org/)。凭证缺失时，
让用户打开[知乎开放平台个人中心](https://developer.zhihu.com/personal)，并只在
自己的终端执行：

```bash
uvx zhihu-search --save-token "<Access Secret>"
uvx zhihu-search --probe
```

`--check-token` 不发起上游请求，只显示配置状态和来源，不输出 Secret 片段或
用户凭证路径。`--probe` 会真实调用一次 `hot_list(limit=1)` 并消耗一次请求
额度；用它判断端到端连通性，不要循环探测。

默认进行用户级 Skill 安装：

```bash
uvx zhihu-search install-skill
```

该命令通过 `npx skills` 安装给 Codex。其他客户端可重复使用
`--agent <名称>`；只有用户明确要求项目隔离时才加 `--project`。

安装后让目标 Agent 重新加载 Skill，再发送：

> 帮我查一下最近主流的 RAG 评测方法在中文开发者社区的讨论，返回 2 条并附来源链接。

在支持 Skill 自动触发的客户端中，验收以下结果：

- 没有生硬点名知乎也能识别这是中文社区研究需求；
- 只走一条匹配的 `search` 路由；
- 返回非空结果、标题和可检查的来源链接；
- 没有为了这次查询额外安装或启动 MCP。

如果当前会话已经暴露匹配的知乎 MCP 工具，Skill 可以直接复用；调用成功后
不要再运行一遍 CLI。

## 2. 仅在高频需求下配置 MCP

先确认用户确实需要常驻集成，并了解目标客户端的进程生命周期。普通、低频
查询停在上一节即可。

默认服务配置：

```text
command: uvx
args:    zhihu-search serve --tools compact
```

| 档位 | 行为 |
|---|---|
| `compact` | `search`、`ask`、`trending`、`other` |
| `knowledge` | compact 加 3 个知识库工具 |
| `user` | compact 加 5 个用户数据工具 |
| `office` | compact 加 4 个 PDF/PPT 工具 |
| `full` | 16 个业务/账号工具加 `other`，共 17 个 |

档位和工具名可用逗号组合；只写工具名时是严格 allowlist。`other` 只能在当前
会话和启动允许范围内执行 `enable`、`disable`、`reset`。
`ZHIHU_MCP_TOOLS` 可以设置默认值，但 `--tools` 优先。

按客户端读取具体配置：

| 客户端 | 指南 |
|---|---|
| Codex | [setup/codex.md](setup/codex.md) |
| Claude Code | [setup/claude-code.md](setup/claude-code.md) |
| OpenCode | [setup/opencode.md](setup/opencode.md) |
| HanaAgent / OpenHanako | [setup/hanako-agent.md](setup/hanako-agent.md) |

### 配置验收清单

1. 保留所有已有 MCP server，只新增或更新 `zhihu`。
2. 不把任何知乎凭证写进客户端配置。
3. 写入前后都解析 JSON 或 TOML，避免损坏用户原有配置。
4. 在目标用户上下文中检查注册结果；不要只把“已添加”的提示当成成功证据。
5. 新建或重新打开客户端任务，让工具目录重新加载。
6. 用一条真实资料查询确认 `search` 成功并返回链接。

工具数量应为：compact 4 个、knowledge 7 个、office 8 个、user 9 个、full
17 个。不要擅自结束用户的客户端进程。

## 3. DeepSeek Harness：安装同一份 Skill

目标客户端是 DSH 时，用原生 bundle 代替通用 Skill 安装步骤：

```bash
dsh plugin --profile web add "github:klarkxy/zhihu-search"
dsh --profile web --dump-config
```

配置结果应包含 `zhihu-search-skill` 和
`@deepseek-ai/dsh-skill-filesystem`。持久安装后重启目标 profile，确认 Skill
目录出现 `zhihu-search`，再让 Agent 按需执行一次真实查询。

bundle 不保存知乎凭证，也不启动 MCP。不要手写 profile patch，也不要因为
安装了 bundle 就再注册常驻 MCP。完整流程见 [setup/dsh.md](setup/dsh.md)。

## 4. 直接 CLI 和 OpenWebUI

客户端不支持 Skill，或用户明确需要脚本调用时，直接运行：

```bash
uvx zhihu-search search "RAG 评测方法" --count 2
```

只有用户明确需要 HTTP OpenAPI 工具服务器时，才考虑 OpenWebUI：

```bash
uvx zhihu-search openwebui \
  --host 0.0.0.0 --port 8000 --api-key "<服务访问口令>"
```

无访问口令时只能监听 localhost 或受控私网。

## 排障与清理

| 症状 | 建议处理 |
|---|---|
| 找不到 `uvx` | 安装 uv 并重新打开终端 |
| `--probe` 失败 | 检查凭证和网络，避免循环请求 |
| MCP 工具数不对 | 检查 `--tools`、`ZHIHU_MCP_TOOLS` 后重启客户端 |
| 返回 `Code=30002` | 用 `--quota` 查看官方剩余额度，再检查接口权限 |
| OAuth 用户调用失败 | 在服务端配置 `ZHIHU_OAUTH_TOKEN` |
| PDF/PPT 长期处理中 | 稍后再查状态，不要紧密轮询 |

明确收到删除凭证的请求后，才运行：

```bash
uvx zhihu-search --clear-token
```

`uvx` 是按需运行，不需要另外卸载 Python 包。
