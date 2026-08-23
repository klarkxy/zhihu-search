# HanaAgent / OpenHanako 配置

先完成 [通用准备](README.md)。

## 配置

打开 `~/.hanako/plugin-data/mcp/config.json`，在 `global.mcp.connectors` 数组中加入：

只有 OpenHanako 开发环境才使用 `~/.hanako-dev/...`。

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

保留数组中已有的其他 connector，不要把 Access Secret 或 OAuth token 写进这里。首次连接后，HanaAgent 会自动读取工具列表。
建有知乎知识库时将 `compact` 改为 `knowledge`，避免私有文档检索被静默
退回全网搜索；用户数据用 `user`，PDF/PPT 用 `office`，一次暴露全部 16
个工具用 `full`。档位与工具名也可逗号混写。完整开关见
[通用安装说明](README.md#4-mcp高频集成)。

## 重启

关闭并重新打开 HanaAgent / OpenHanako。

## 验证

发送：

> 用 zhihu 搜索知乎上的“RAG 评测方法”，返回 3 条结果。

如果 connector 未启动、工具为空或调用失败，查看 [通用排障](README.md#维护与排障)。
