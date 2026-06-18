# Claude Code 安装指南

## 目标

在 Claude Code 中接入 `zhihu-search` MCP 服务器，可使用 `search`、`ask`、`trending` 三个工具。

## 前提

已完成 [通用准备](../setup/README.md) 中的凭证保存和连通性验证。

## 配置文件位置

Claude Code 支持两种配置方式：

- **全局**：`~/.claude.json`（任何项目都可用）
- **项目级**：`<当前目录>/.mcp.json`（仅当前项目可用）

默认推荐**全局配置**。

## 配置内容

打开 `~/.claude.json`，在 `mcpServers` 字段下新增 `zhihu` 条目（保留已有的 `playwright`、`context7` 等条目）：

```json
{
  "mcpServers": {
    "zhihu": {
      "type": "stdio",
      "command": "uvx",
      "args": ["zhihu-search"],
      "env": {}
    }
  }
}
```

> 如果你用本地源码安装，把 `command` / `args` 换成 `zhihu-search` 的本地路径：
> ```json
> "command": "zhihu-search",
> "args": []
> ```

## 重启

关闭并重新打开 Claude Code 客户端（或终端里 `Ctrl+C` 后重新启动 `claude`）。

## 验证

在 Claude Code 中发送以下指令，确认三个工具都能正常调用：

```
用 mcp__zhihu__search 搜 "RAG 检索增强生成"，count 2
```

```
用 mcp__zhihu__ask 问 "什么是 ReAct Agent"
```

```
用 mcp__zhihu__trending 看看热榜前 5
```

每条返回末尾应包含 `配额：搜索 x/5000 · 热榜 x/100 · 直答 x/100`，即表示成功。

## 升级

```bash
uvx --upgrade zhihu-search
```

## 排障

| 症状 | 排查 |
|---|---|
| `tool not found` | 确认已重启 Claude Code；检查配置文件位置是否对应当前项目 |
| `Token 已过期或无效` | 回通用准备重新执行 `--save-token` |
| `command not found: uvx` | 先安装 uv |
