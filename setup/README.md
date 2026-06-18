# 安装指南索引

本项目支持以下 MCP 客户端。根据你使用的工具，选择对应的安装指南：

| 客户端 | 指南文件 | 配置文件位置 |
|---|---|---|
| Claude Code | [claude-code.md](./claude-code.md) | `~/.claude.json`（全局）或项目级 `.mcp.json` |
| Codex | [codex.md](./codex.md) | `~/.codex/config.toml` |
| HanaAgent | [hanako-agent.md](./hanako-agent.md) | `~/.hanako-dev/plugin-data/mcp/config.json` |
| OpenCode | [opencode.md](./opencode.md) | `~/.config/opencode/opencode.json` |
| 其他 / 通用准备 | [SETUP.md](./SETUP.md) | 凭证保存、验证、排障 |

所有客户端共用同一份凭证（`~/.config/zhihu-search/credentials.json`），先完成 [通用准备](./SETUP.md)，再写入客户端配置。
