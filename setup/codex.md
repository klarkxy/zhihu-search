# Codex 安装指南

## 目标

在 Codex 中接入 `zhihu-search` MCP 服务器。

## 前提

已完成 [通用准备](../setup/README.md) 中的凭证保存和连通性验证。

## 配置文件位置

Codex 的 MCP 配置在 `~/.codex/config.toml` 的 `[mcp_servers]` 段下。

## 配置内容

在 `~/.codex/config.toml` 中找到 `[mcp_servers]` 段，在其下新增：

```toml
[mcp_servers.zhihu]
type = "stdio"
command = "zhihu-search"
args = []
env = {}
```

完整示例（保留已有的 `[mcp_servers.node_repl]`）：

```toml
[mcp_servers]

[mcp_servers.zhihu]
type = "stdio"
command = "zhihu-search"
args = []
env = {}

[mcp_servers.node_repl]
type = "stdio"
command = 'C:\Users\...\node_repl.exe'
startup_timeout_sec = 120
...
```

> 如果 `zhihu-search` 不在 PATH 上，用 `python -m zhihu_search` 或写绝对路径：
> ```toml
> command = "C:\Users\<你的用户名>\AppData\Local\Programs\Python\Python313\Scripts\zhihu-search.exe"
> ```

## 重启

关闭并重新打开 Codex 客户端（或重启 Codex 扩展）。

## 验证

在 Codex 中发送：

```
用 zhihu search 搜 "RAG"
```

```
用 zhihu ask 问 "什么是 ReAct"
```

```
用 zhihu trending 看热榜
```

> Codex 的 tool 调用语法取决于其内部 MCP 集成方式，通常直接说 "用 zhihu search ..." 即可。

## 排障

| 症状 | 排查 |
|---|---|
| MCP 启动超时 | 检查 `zhihu-search` 是否在 PATH；TOML 语法是否合法 |
| `Token 已过期或无效` | 回通用准备重新执行 `--save-token` |
| 工具未出现 | 确认已重启 Codex；检查 `[mcp_servers]` 段是否在文件顶层（非嵌套在 `[projects]` 下） |
