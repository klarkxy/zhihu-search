# OpenCode 配置

先完成 [通用准备](README.md)。

## 配置

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

保留文件中已有的其他配置，不要把 Access Secret 或 OAuth token 写进这里。
建有知乎知识库时将 `compact` 改为 `knowledge`，避免私有文档检索被静默
退回全网搜索；用户数据用 `user`，PDF/PPT 用 `office`，一次暴露全部 16
个工具用 `full`。档位与工具名也可逗号混写。完整开关见
[通用安装说明](README.md#4-mcp高频集成)。

## 重启

关闭并重新打开 OpenCode。

## 验证

发送：

> 用 zhihu 搜索知乎上的“RAG 评测方法”，返回 3 条结果。

如果工具没有出现或调用失败，查看 [通用排障](README.md#维护与排障)。
