# HanaAgent / OpenHanako 配置

先看[通用安装说明](README.md)。如果当前环境支持 Skill，优先安装 Skill；下面
的 MCP connector 会自动启动和重连，只适合高频、持续调用。

## 可选：配置 MCP connector

打开 `~/.hanako/plugin-data/mcp/config.json`，在
`global.mcp.connectors` 数组中加入以下对象。只有 OpenHanako 开发环境才使用
`~/.hanako-dev/...`。

```json
{
  "id": "zhihu",
  "name": "zhihu",
  "description": "知乎开放平台 MCP",
  "transport": "stdio",
  "command": "uvx",
  "args": ["zhihu-search", "serve", "--tools", "compact"],
  "env": {},
  "autoStart": true,
  "autoReconnect": true
}
```

保留数组中的其他 connector，不要把 Access Secret 或 OAuth token 写进配置。
`compact` 是默认档位；知识库选 `knowledge`，用户数据选 `user`，PDF/PPT 选
`office`，全部 17 个 MCP 工具选 `full`。详细语义见
[MCP 高频集成](README.md#2-mcp高频集成)。

## 重启与验证

关闭并重新打开 HanaAgent / OpenHanako，然后发送：

> 用 zhihu 搜索知乎上的“RAG 评测方法”，返回 3 条结果并附链接。

connector 未启动、工具为空或调用失败时，查看
[通用排障](README.md#维护与排障)。
