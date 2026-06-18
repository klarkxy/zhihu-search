# OpenCode 安装指南

## 目标

在 OpenCode 中接入 `zhihu-search` MCP 服务器。

## 前提

已完成 [通用准备](../setup/README.md) 中的凭证保存和连通性验证。

## 配置文件位置

OpenCode 的 MCP 配置在 `~/.config/opencode/opencode.json`（或 `opencode.jsonc`）。

支持 JSON 和 JSONC（带注释的 JSON）格式。如果文件不存在，直接创建即可。

## 配置内容

在 `~/.config/opencode/opencode.json` 中添加 `mcp` 字段：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "zhihu": {
      "type": "local",
      "command": ["zhihu-search"],
      "enabled": true,
      "environment": {}
    }
  }
}
```

> `command` 是**数组**，每个元素是命令的一部分。如果 `zhihu-search` 不在 PATH，写绝对路径：
> ```json
> "command": ["C:\\Users\\<用户名>\\AppData\\Local\\Programs\\Python\\Python313\\Scripts\\zhihu-search.exe"]
> ```

如果配置文件中已有其他字段（如 `provider`、`skills` 等），保留它们，只添加 `mcp` 字段。

## 重启

关闭并重新打开 OpenCode（或终端里重新启动 `opencode`）。

## 验证

在 OpenCode 中发送：

```
用 zhihu search 搜索 "RAG"
```

```
用 zhihu ask 问 "什么是 ReAct"
```

```
用 zhihu trending 看热榜
```

> OpenCode 的 tool 调用语法取决于其内部 MCP 集成方式，通常直接说 "用 zhihu search ..." 即可。

## 排障

| 症状 | 排查 |
|---|---|
| 工具未出现 | 确认已重启 OpenCode；检查 JSON 语法是否合法（可用 jsonlint 验证） |
| `command not found` | 检查 `zhihu-search` 是否在 PATH；或改用绝对路径 |
| `Token 已过期或无效` | 回通用准备重新执行 `--save-token` |
| 超时 | 默认值 5000ms，可添加 `"timeout": 10000` 到 `mcp.zhihu` 中 |
