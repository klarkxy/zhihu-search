# Codex 配置

先完成 [通用准备](README.md)。

## 配置

推荐直接执行：

```bash
codex mcp add zhihu -- uvx zhihu-search serve --tools compact
```

也可以手动在 `~/.codex/config.toml` 中加入：

```toml
[mcp_servers.zhihu]
command = "uvx"
args = ["zhihu-search", "serve", "--tools", "compact"]
```

保留文件中已有的其他配置，不要把 Access Secret 或 OAuth token 写进这里。
如需一次暴露全部 13 个工具，将 `compact` 改为 `full`；其他开关见
[通用安装说明](README.md#3-配置-mcp高频使用)。

## 重启

关闭并重新打开 Codex。

## 验证

发送：

> 用 zhihu 搜索知乎上的“RAG 评测方法”，返回 3 条结果。

如果工具没有出现或调用失败，查看 [通用排障](README.md#通用排障)。
