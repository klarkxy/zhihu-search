# zhihu-search

知乎开放平台的 stdio MCP 服务器。安装后，MCP 客户端可以直接调用 `search`、`ask`、`trending` 三个工具，完成知乎站内搜索、全网搜索、直答和热榜查询。

---

## 快速交给 AI agent 安装

把下面整段复制给你的 agent（Claude Code、Cursor、Codex 等能读文件和执行命令的环境都可以），它会按安装手册一步步处理：

```
请帮我安装并配置 zhihu-search MCP 服务器。

1. 先读这份安装指南：https://raw.githubusercontent.com/klarkxy/zhihu-search/main/AGENT_SETUP.md
2. 按里面的 8 个步骤一步步执行。
3. 引导我去 https://developer.zhihu.com/personal 创建 Access Secret。
4. 不要让我把 Access Secret 发到聊天里；让我在终端里本地执行保存命令。
5. 重启 MCP 客户端后，用 search/ask/trending 工具做一次端到端验证。
6. 把每一步执行结果告诉我，遇到问题停下来问我。

我用的客户端：Claude Code（或 Cursor / 其他，按实际情况改）
```

这是终端用户路径。你只需要打开知乎开放平台创建 Access Secret，然后按 agent 给出的本地命令保存凭证。Access Secret 不应该出现在聊天记录、截图或公开仓库里。

---

## 项目做什么

知乎开放平台 [https://developer.zhihu.com](https://developer.zhihu.com) 提供了 4 个数据接口：

| 名称       | 路径                                            | 用途                                |
|------------|-------------------------------------------------|-------------------------------------|
| 知乎搜索   | `GET /api/v1/content/zhihu_search`              | 站内搜索（问题、回答、文章、用户）  |
| 全网搜索   | `GET /api/v1/content/global_search`             | 全网搜索（支持 filter 表达式）      |
| 直答       | `POST /v1/chat/completions`                     | 调用知乎自研大模型                  |
| 热榜       | `GET /api/v1/content/hot_list`                  | 当前知乎热榜                        |

本项目把这 4 个接口封装成一个 stdio MCP 服务器，对外暴露 3 个按用户意图分组的工具：

| 工具       | 背后转发到                                      | 适用场景                  |
|------------|-------------------------------------------------|---------------------------|
| `search`   | 知乎搜索（scope=zhihu）/ 全网搜索（scope=web）   | 找内容                    |
| `ask`      | 直答（chat completions）                        | 让模型回答问题            |
| `trending` | 热榜                                            | 看当前热榜                |

项目不重新实现上游接口，只做参数校验、HTTP 转发、错误翻译、配额提示和 Markdown 格式化。这样代码量小，行为更接近知乎官方接口，排障路径也更短。

每次成功返回的末尾会附一行本地配额进度，让你和 agent 随时知道今日大约还剩多少次调用。

---

## 开发者模式

```bash
git clone <repo-url> zhihu-search
cd zhihu-search
pip install -e ".[dev]"
```

或者本地已有源码：

```bash
cd zhihu-search
pip install -e ".[dev]"
```

运行测试：

```bash
pytest                # 离线单元测试
pytest -v             # 每个用例详情
```

单元测试使用 mock，不需要真实 Access Secret。端到端探测需要先保存凭证或设置 `ZHIHU_ACCESS_SECRET`。

```bash
zhihu-search --check-token
zhihu-search --probe
```

## 凭证与安全

`zhihu-search` 按以下优先级读取 Access Secret：

1. `ZHIHU_ACCESS_SECRET` 环境变量
2. `~/.config/zhihu-search/credentials.json`

推荐通过本地命令保存凭证：

```bash
zhihu-search --save-token "<你的 Access Secret>"
zhihu-search --check-token
```

凭证文件是本机明文 JSON。不要把 Access Secret 写进聊天记录、`.mcp.json`、日志、截图或仓库。如果需要移除本地凭证：

```bash
zhihu-search --clear-token
```

---

## 工具说明

### `search(query, scope="zhihu"|"web", count=10, filter="")`

- `scope="zhihu"`：知乎站内，最多 10 条
- `scope="web"`：全网，最多 20 条，可传 `filter` 表达式，例如 `host=="example.com" AND publish_time>=1778494631`

返回 Markdown 文本：标题、链接、作者、权威等级、赞同数、评论数、摘要。

### `ask(query, model="fast"|"thinking"|"agent")`

转发到知乎直答（OpenAI 兼容 chat completions）：

- `fast` → `zhida-fast-1p5`，日常用这个
- `thinking` → `zhida-thinking-1p5`，带思考过程的深度回答
- `agent` → `zhida-agent`，可能耗时 30 秒以上，会触发工具调用

如启用 thinking，会同时返回「思考过程」和「最终回答」。

### `trending(limit=30)`

当前知乎热榜，含标题、链接、封面、摘要。

---

## 本地配额提示

知乎官方文档没有稳定说明 `X-RateLimit-*` 响应头。本项目维护一份本地调用计数（`~/.config/zhihu-search/quota.json`），每天 0 点自动重置。

```bash
zhihu-search --quota          # 看当前用量
zhihu-search --reset-quota    # 清零今日计数（调试用）

# 改每日上限（默认 1000）
export ZHIHU_DAILY_LIMIT=5000
```

每次返回内容末尾会附一行：

```
配额：今日已用 12/1000，剩余 988 次（2026-06-19T00:00:00 刷新）
```

如果上游返回真实限流错误（响应信封 `Code=30001` 或 HTTP 429），工具会返回可读错误，并尽量带上 `retry-after` 提示。

---

## 架构

```
MCP 客户端（Claude Code / Cursor / ...）
    │  stdio
    ▼
server.py（FastMCP）
    │  search / ask / trending （3 个分组工具）
    ▼
ZhihuRestClient（统一 HTTP REST 客户端）
    │
    ▼
developer.zhihu.com（Bearer + X-Request-Timestamp）
```

HTTP REST 比 MCP-over-SSE 简单一截：每个请求独立，无长连接、无重连逻辑、无消息派发。每个工具调用 = 一次 HTTP 请求 + 一次配额计数 + 一次响应组装。

---

## 当前边界

当前不包含缓存、客户端侧限流、多账号、系统 keyring / DPAPI 加密凭证、PyInstaller 单文件、HTTP transport 和 `tool annotations`。这些能力可以在后续需要时增量加入。

---

## 许可证

[SATA License v2.0](./LICENSE)（Star And Thank Author License）。
