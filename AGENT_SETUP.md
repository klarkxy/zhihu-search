# Agent 安装与验证指南

默认安装 `zhihu-search` Skill。CLI 适合临时调用；只有用户明确表示会高频
使用时才配置 MCP；OpenWebUI 放在最后考虑。

完成标准：目标入口真实调用成功，且所有密钥都没有进入聊天、日志或客户端
配置。

## 安全规则

- 不要让用户在聊天中粘贴任何密钥。
- Access Secret 只保存在本机凭证文件或进程环境中。
- `ZHIHU_OAUTH_TOKEN` 只放在服务端；模型只接收
  `use_configured_oauth_user` 布尔开关。
- `pdf-upload`、`oauth-url` 和 `oauth-token` 只允许从 CLI/Python 调用。
- MCP 不接收本机文件路径、OAuth `app_key` 或 OAuth token。

## 1. 准备 uvx 和凭证

```bash
uvx --version
uvx zhihu-search --check-token
```

找不到 `uvx` 时先安装 [uv](https://docs.astral.sh/uv/)。凭证缺失时，让
用户打开 [知乎开放平台个人中心](https://developer.zhihu.com/personal)
创建 Access Secret，并只在自己的终端保存：

```bash
uvx zhihu-search --save-token "<Access Secret>"
uvx zhihu-search --probe
```

`--check-token` 只证明凭证可读取；必须以 `--probe` 的真实上游响应作为
连通性判断。

## 2. 优先安装 Skill

```bash
npx skills add klarkxy/zhihu-search --skill zhihu-search
```

让目标 Agent 重新加载 Skill，然后真实执行一次查询：

> 使用 zhihu-search 搜索知乎上的“RAG 评测方法”，返回 2 条并附链接。

Skill 能被发现、查询成功且返回链接，即完成默认安装。不要为了单次任务继续
安装 MCP。

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
| `full` | 暴露全部 13 个工具 |
| 逗号 allowlist | 严格只允许指定工具 |

`other` 的 `enable`、`disable`、`reset` 只改变当前 MCP 会话，可展开、收起
或复原低频显式工具。compact/full 可管理全部 9 个；自定义 allowlist
只能管理其中已允许的工具，不能越过启动开关。`ZHIHU_MCP_TOOLS`
可设置默认值，但命令行 `--tools` 优先。

写入配置时：

1. 保留所有已有 MCP server，只新增或更新 `zhihu`。
2. 不写入任何知乎凭证。
3. 写前、写后都解析 JSON 或 TOML。
4. 让用户重启客户端，再验证工具列表和一次真实 `search`。

compact 启动时应看到 4 个工具；full 启动时应看到 13 个。不要擅自结束
用户的客户端进程。

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
| `Code=30002` | 到知乎开放平台检查额度或接口权限 |
| OAuth 用户调用失败 | 在服务端配置 `ZHIHU_OAUTH_TOKEN` |
| PDF/PPT 长期处理中 | 稍后查询状态，不要紧密轮询 |

移除本机凭证：

```bash
uvx zhihu-search --clear-token
```

`uvx` 是按需运行，不需要卸载 Python 包。
