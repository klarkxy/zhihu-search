# HanaAgent 安装指南

## 目标

在 HanaAgent（OpenHanako）中接入 `zhihu-search` MCP 服务器，使其通过 `mcp_connectors_status` 可见。

## 前提

已完成 [通用准备](../setup/README.md) 中的凭证保存和连通性验证。

## 配置文件位置

HanaAgent 的 MCP connector 配置在：

```
~/.hanako-dev/plugin-data/mcp/config.json
```

这是一个 JSON 文件，connector 定义在 `global.mcp.connectors` 数组中。

## 配置内容

在 `connectors` 数组末尾新增一个对象（保留已有的 `MiniMax`、`MiniMax-MCP`、`context7` 等条目）：

```json
{
  "id": "zhihu",
  "name": "zhihu",
  "description": "知乎开放平台 MCP 封装",
  "transport": "stdio",
  "url": "",
  "command": "zhihu-search",
  "args": [],
  "cwd": "",
  "env": {},
  "headers": {},
  "registryUrl": "",
  "timeout": 0,
  "authType": "none",
  "authorizationToken": "",
  "oauthClientId": "",
  "oauthClientSecret": "",
  "clientIdSource": "",
  "oauth": {
    "accessToken": "",
    "refreshToken": "",
    "tokenType": "",
    "tokenEndpoint": "",
    "scope": "",
    "expiresIn": 0,
    "expiresAt": 0,
    "obtainedAt": 0
  },
  "autoStart": true,
  "autoReconnect": true,
  "tools": []
}
```

`tools` 初始为空，HanaAgent 首次连接成功后会自动从 MCP 服务器拉取工具列表并填充。

> 如果 `zhihu-search` 不在 PATH 上，用绝对路径：
> ```json
> "command": "C:\\Users\\<用户名>\\AppData\\Local\\Programs\\Python\\Python313\\Scripts\\zhihu-search.exe"
> ```

## 重启

关闭并重新打开 HanaAgent 桌面端。connector 在启动时自动加载。

## 验证

重启后，在 HanaAgent 对话中发送：

```
搜索知乎上 "RAG 检索增强生成"
```

```
问知乎直答 "什么是 ReAct Agent"
```

```
看看知乎热榜
```

如果 HanaAgent 的工具列表中出现了 `mcp__zhihu-search__search`、`mcp__zhihu-search__ask`、`mcp__zhihu-search__trending`，即表示成功。

## 排障

| 症状 | 排查 |
|---|---|
| `mcp_connectors_status` 中无 `zhihu` | 确认配置文件已保存；确认已重启 HanaAgent |
| connector 状态 `stopped` | 检查 `command` 路径是否正确；在终端直接运行 `zhihu-search --check-token` 看是否报错 |
| `Token 已过期或无效` | 回通用准备重新执行 `--save-token` |
| 工具列表为空 | 首次连接后需等待几秒；如长时间为空，检查 stderr 日志 |
