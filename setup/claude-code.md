# Claude Code 配置

先看[通用安装说明](README.md)。如果当前 Claude Code 环境支持 Skill，优先
安装 Skill；下面的 MCP 配置只适合高频、持续调用。

## 可选：配置 MCP

在全局 `~/.claude.json` 或项目级 `.mcp.json` 的 `mcpServers` 中加入：

```json
{
  "mcpServers": {
    "zhihu": {
      "type": "stdio",
      "command": "uvx",
      "args": ["zhihu-search", "serve", "--tools", "compact"]
    }
  }
}
```

保留原有配置，不要把 Access Secret 或 OAuth token 写进文件。`compact` 是
默认档位；知识库选 `knowledge`，用户数据选 `user`，PDF/PPT 选 `office`，
全部 17 个 MCP 工具选 `full`。详细语义见
[MCP 高频集成](README.md#2-mcp高频集成)。

## 重启与验证

关闭并重新打开 Claude Code，然后发送：

> 用 zhihu 搜索知乎上的“RAG 评测方法”，返回 3 条结果并附链接。

工具未出现或调用失败时，查看[通用排障](README.md#维护与排障)。
