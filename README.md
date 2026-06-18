# zhihu-search

知乎开放平台的 stdio MCP 服务器。安装后，MCP 客户端可直接调用 `search`、`ask`、`trending` 三个工具，完成知乎站内搜索、全网搜索、知乎直答和热榜查询。

---

## 快速安装

### 让 AI 一键装好

复制这段 prompt 给你的 AI 编程助手（Claude Code、Cursor、Codex、OpenCode 等），它会自动完成：

> 请帮我安装并配置 zhihu-search 这个 MCP 服务器。先读取 https://raw.githubusercontent.com/klarkxy/zhihu-search/main/AGENT_SETUP.md，按步骤执行。Access Secret 不要发到聊天里，让我在本地终端执行保存命令。

### 手动安装

先完成 [通用准备](setup/SETUP.md)（存凭证、验证连通性），再选对应客户端写入配置：

| 客户端 | 安装指南 |
|---|---|
| Claude Code | [setup/claude-code.md](setup/claude-code.md) |
| Codex | [setup/codex.md](setup/codex.md) |
| HanaAgent | [setup/hanako-agent.md](setup/hanako-agent.md) |
| OpenCode | [setup/opencode.md](setup/opencode.md) |
| 其他 | [setup/SETUP.md](setup/SETUP.md) 中的通用配置 |

**安全提醒**：Access Secret 是你的知乎开发者凭证，永远不要粘贴到聊天记录、截图或公开仓库。

---

## 项目做什么

知乎开放平台 [developer.zhihu.com](https://developer.zhihu.com) 提供 4 个数据接口：

| 接口 | 路径 | 说明 |
|---|---|---|
| 知乎搜索 | `GET /api/v1/content/zhihu_search` | 站内搜索（问题、回答、文章、用户） |
| 全网搜索 | `GET /api/v1/content/global_search` | 全网搜索（支持 filter 表达式） |
| 直答 | `POST /v1/chat/completions` | 知乎自研大模型对话 |
| 热榜 | `GET /api/v1/content/hot_list` | 当前知乎热榜 |

本项目把这 4 个接口封装成一个 stdio MCP 服务器，对外暴露 3 个工具：

| 工具 | 转发到 | 用途 |
|---|---|---|
| `search` | 知乎搜索 / 全网搜索 | 找内容 |
| `ask` | 直答（chat completions） | 让模型回答问题 |
| `trending` | 热榜 | 查看当前热榜 |

只做参数校验、HTTP 转发、错误翻译、配额提示和 Markdown 格式化，不重新实现上游接口。代码量小，行为贴近知乎官方接口，排障路径短。

---

## 工具说明

### `search(query, scope="zhihu"|"web", count=10, filter="")`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `query` | `str` | 必填 | 搜索关键词，2-100 字符 |
| `scope` | `"zhihu"|"web"` | `"zhihu"` | `zhihu` 站内搜索；`web` 全网搜索 |
| `count` | `int` | `10` | 返回条数；zhihu 上限 10，web 上限 20 |
| `filter` | `str` | `""` | 仅 `scope="web"` 生效，例如 `host=="example.com"` |

返回 Markdown：标题、链接、作者、权威等级、赞同数、评论数、摘要。

### `ask(query, model="fast"|"thinking"|"agent")`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `query` | `str` | 必填 | 问题 |
| `model` | `"fast"|"thinking"|"agent"` | `"fast"` | 模型档位 |

| 档位 | 对应模型 | 特点 |
|---|---|---|
| `fast` | `zhida-fast-1p5` | 日常快速回答 |
| `thinking` | `zhida-thinking-1p5` | 带思考过程的深度回答 |
| `agent` | `zhida-agent` | 可能耗时 30s 以上，会调用工具 |

启用 thinking 时，返回同时包含「思考过程」和「最终回答」。

### `trending(limit=30)`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `limit` | `int` | `30` | 返回条数，上限 30 |

返回当前知乎热榜：标题、链接、封面、摘要。

---

## 凭证与安全

`zhihu-search` 按以下优先级读取 Access Secret：

1. `ZHIHU_ACCESS_SECRET` 环境变量
2. `~/.config/zhihu-search/credentials.json`（推荐）

凭证文件是本机明文 JSON。不要把 Access Secret 写进聊天记录、`.mcp.json`、日志、截图或仓库。存取命令见 [setup/SETUP.md](setup/SETUP.md)。

如需移除本地凭证：`zhihu-search --clear-token`

---

## 本地配额提示

知乎官方没有稳定的 `X-RateLimit-*` 响应头。本项目维护一份本地调用计数（`~/.config/zhihu-search/quota.json`），按接口分桶：

| 类别 | 包含接口 | 默认上限 | 覆盖环境变量 |
|---|---|---|---|
| `search` | 知乎搜索 / 全网搜索 | 5000 | `ZHIHU_DAILY_LIMIT_SEARCH` |
| `trending` | 热榜 | 100 | `ZHIHU_DAILY_LIMIT_TRENDING` |
| `ask` | 直答 | 100 | `ZHIHU_DAILY_LIMIT_ASK` |

旧变量 `ZHIHU_DAILY_LIMIT` 仍可用（三个桶同时设为同一值）。

每次成功返回末尾附加一行配额进度：

```
配额：搜索 12/5000 · 热榜 1/100 · 直答 0/100（2026-06-19T00:00:00 刷新）
```

---

## 开发者模式

```bash
git clone https://github.com/klarkxy/zhihu-search
cd zhihu-search
python -m pip install -e ".[dev]"
```

```bash
pytest          # 离线单元测试
pytest -v      # 详细输出
zhihu-search --check-token   # 凭证检查
zhihu-search --probe         # 端到端探测
```

---

## 排障

安装或配置遇到问题，先让 agent 读 [AGENT_SETUP.md](AGENT_SETUP.md)（agent 用）或 [setup/SETUP.md](setup/SETUP.md)（用户手动安装）。

| 症状 | 处理位置 |
|---|---|
| `command not found: uvx` | setup/SETUP.md |
| Token 无效 / 过期 | setup/SETUP.md |
| 客户端找不到工具 | 对应客户端的 setup/*.md |
| 配额显示 `剩余: 0` | 等次日或提高上限 |

---

## 架构

```
MCP 客户端（Claude Code / Cursor / ...）
    │  stdio
    ▼
server.py（FastMCP）
    │  search / ask / trending
    ▼
ZhihuRestClient（统一 HTTP REST 客户端）
    │
    ▼
developer.zhihu.com（Bearer + X-Request-Timestamp）
```

HTTP REST 比 SSE 简单：每个请求独立，无长连接、无重连逻辑。每个工具调用 = 一次 HTTP 请求 + 一次配额计数 + 一次响应组装。

---

## 当前边界

不包含缓存、客户端侧限流、多账号、系统 keyring / DPAPI 加密凭证、PyInstaller 单文件、HTTP transport 和 `tool annotations`。后续按需增量加入。

---

## 许可证

[SATA License v2.0](LICENSE)（Star And Thank Author License）。
