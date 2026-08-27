# OpenCode 配置

先看[通用安装说明](README.md)。如果当前 OpenCode 环境支持 Skill，优先安装
Skill；下面的 MCP 配置只适合高频、持续调用。

## 可选：配置 MCP

在 `~/.config/opencode/opencode.json`（或 `opencode.jsonc`）的 `mcp` 中加入：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "zhihu": {
      "type": "local",
      "command": ["uvx", "zhihu-search", "serve", "--tools", "compact"],
      "enabled": true
    }
  }
}
```

保留原有配置，不要把 Access Secret 或 OAuth token 写进文件。`compact` 是
默认档位；知识库选 `knowledge`，用户数据选 `user`，PDF/PPT 选 `office`，
全部 17 个 MCP 工具选 `full`。详细语义见
[MCP 高频集成](README.md#2-mcp高频集成)。

## 重启与验证

关闭并重新打开 OpenCode，然后发送：

> 用 zhihu 搜索知乎上的“RAG 评测方法”，返回 3 条结果并附链接。

工具未出现或调用失败时，查看[通用排障](README.md#维护与排障)。
