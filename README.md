# zhihu-search

知乎开放平台的 stdio MCP 服务器。安装后，MCP 客户端可直接调用 `search`、`ask`、`trending` 三个工具，完成知乎站内搜索、全网搜索、知乎直答和热榜查询。

---

## 不会装？让 AI 帮你一键装好

如果你不太熟悉命令行、MCP 或 Python，**完全不用自己折腾**。把下面这段文字复制给你的 AI 编程助手（Claude Code、Cursor、Windsurf、GitHub Copilot、OpenCode、Codex、Cline / Roo Code、Augment Code、Aider、Codeium 等都可以），它会读取安装手册并一步步帮你完成。

```
请帮我安装并配置 zhihu-search 这个 MCP 服务器。

1. 先读取这份安装指南：https://raw.githubusercontent.com/klarkxy/zhihu-search/main/AGENT_SETUP.md
2. 按照指南里的顺序执行，默认用 uvx 模式安装。
3. 带我去 https://developer.zhihu.com/personal 创建 Access Secret。
4. 重要：不要把 Access Secret 发到聊天里，让我只在本地终端执行保存命令。
5. 装好后，帮我写入当前客户端对应的 MCP 配置文件。你可以根据 system / context 判断当前环境（Claude Code、Cursor、Windsurf、OpenCode、Codex、Cline 等）；如果判断不了，再问我。
6. 重启 MCP 客户端后，用 search、ask、trending 各做一次真实调用，确认能用。
7. 每一步都告诉我结果，遇到需要我操作或确认的地方停下来问我。
```

> **安全提醒**：Access Secret 是你的知乎开发者凭证，**永远不要把它粘贴到聊天记录、截图或公开仓库**。AI 助手只会让你在本地终端执行保存命令， secret 只会存在你电脑上的 `~/.config/zhihu-search/credentials.json` 里。

如果你习惯自己动手，也可以直接看下面的「5 分钟安装」。

---

## 5 分钟安装（uvx，推荐）

```bash
# 1. 安装 uv（如已安装可跳过）
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. 保存 Access Secret（只首次需要）
uvx --from git+https://github.com/klarkxy/zhihu-search zhihu-search --save-token "<你的 Access Secret>"
```

> **安全提示**：Access Secret 不要发到聊天、截图或公开仓库。只在本地终端执行保存命令。

## MCP 配置示例

按你用的客户端选一种，写入对应文件即可：

### Claude Code

项目级：`<当前目录>/.mcp.json`

```json
{
  "mcpServers": {
    "zhihu": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/klarkxy/zhihu-search", "zhihu-search"],
      "env": {}
    }
  }
}
```

全局：`~/.claude.json`（格式同上）。

### Cursor

项目级：`<当前目录>/.cursor/mcp.json`

全局：`~/.cursor/mcp.json`

### 其他客户端

参考上面的 `command` / `args` / `env` 三项即可。本项目是 stdio 服务器，不需要 SSE/HTTP。

> 项目还没发到 PyPI，所以包来源用 `git+https://github.com/klarkxy/zhihu-search`。上线后可直接写 `zhihu-search`（不带 `--from`）或锁定版本 `zhihu-search==0.1.0`。

### 升级

```bash
uvx --upgrade --from git+https://github.com/klarkxy/zhihu-search zhihu-search
```

---

## 项目做什么

知乎开放平台 [developer.zhihu.com](https://developer.zhihu.com) 提供 4 个数据接口：

| 接口       | 路径                                 | 说明                          |
|------------|--------------------------------------|-------------------------------|
| 知乎搜索   | `GET /api/v1/content/zhihu_search`   | 站内搜索（问题、回答、文章、用户） |
| 全网搜索   | `GET /api/v1/content/global_search`  | 全网搜索（支持 filter 表达式）    |
| 直答       | `POST /v1/chat/completions`          | 知乎自研大模型对话               |
| 热榜       | `GET /api/v1/content/hot_list`       | 当前知乎热榜                    |

本项目把这 4 个接口封装成一个 stdio MCP 服务器，对外暴露 3 个工具：

| 工具       | 转发到                          | 用途                  |
|------------|---------------------------------|-----------------------|
| `search`   | 知乎搜索 / 全网搜索              | 找内容                |
| `ask`      | 直答（chat completions）         | 让模型回答问题         |
| `trending` | 热榜                             | 查看当前热榜           |

本项目只做参数校验、HTTP 转发、错误翻译、配额提示和 Markdown 格式化，不重新实现上游接口。代码量小，行为贴近知乎官方接口，排障路径短。

---

## 工具说明

### `search(query, scope="zhihu"|"web", count=10, filter="")`

| 参数    | 类型              | 默认值   | 说明                                                |
|---------|-------------------|----------|-----------------------------------------------------|
| `query` | `str`             | 必填     | 搜索关键词，2-100 字符                               |
| `scope` | `"zhihu"|"web"`   | `"zhihu"` | `zhihu` 站内搜索；`web` 全网搜索                    |
| `count` | `int`             | `10`     | 返回条数；zhihu 上限 10，web 上限 20                 |
| `filter`| `str`             | `""`     | 仅 `scope="web"` 生效，例如 `host=="example.com"` |

返回 Markdown：标题、链接、作者、权威等级、赞同数、评论数、摘要。

### `ask(query, model="fast"|"thinking"|"agent")`

| 参数    | 类型                       | 默认值    | 说明                                                |
|---------|----------------------------|-----------|-----------------------------------------------------|
| `query` | `str`                      | 必填      | 问题                                                 |
| `model` | `"fast"|"thinking"|"agent"` | `"fast"`  | 模型档位，见下表                                    |

模型映射：

| 档位      | 对应模型                  | 特点                          |
|-----------|---------------------------|-------------------------------|
| `fast`    | `zhida-fast-1p5`          | 日常快速回答                   |
| `thinking`| `zhida-thinking-1p5`      | 带思考过程的深度回答            |
| `agent`   | `zhida-agent`             | 可能耗时 30s 以上，会调用工具   |

启用 thinking 时，返回同时包含「思考过程」和「最终回答」。

### `trending(limit=30)`

| 参数    | 类型  | 默认值 | 说明              |
|---------|-------|--------|-------------------|
| `limit` | `int` | `30`   | 返回条数，上限 30 |

返回当前知乎热榜：标题、链接、封面、摘要。

---

## 凭证与安全

`zhihu-search` 按以下优先级读取 Access Secret：

1. `ZHIHU_ACCESS_SECRET` 环境变量
2. `~/.config/zhihu-search/credentials.json`

推荐通过本地命令保存：

```bash
uvx --from git+https://github.com/klarkxy/zhihu-search zhihu-search --save-token "<你的 Access Secret>"
uvx --from git+https://github.com/klarkxy/zhihu-search zhihu-search --check-token
```

凭证文件是本机明文 JSON。不要把 Access Secret 写进聊天记录、`.mcp.json`、日志、截图或仓库。

如需移除本地凭证：

```bash
uvx --from git+https://github.com/klarkxy/zhihu-search zhihu-search --clear-token
```

---

## 本地配额提示

知乎官方文档没有稳定的 `X-RateLimit-*` 响应头说明。本项目维护一份本地调用计数（`~/.config/zhihu-search/quota.json`），按接口类别分桶统计：

| 类别       | 包含接口            | 默认上限 | 覆盖环境变量                 |
|------------|---------------------|----------|------------------------------|
| `search`   | 知乎搜索 / 全网搜索 | 5000     | `ZHIHU_DAILY_LIMIT_SEARCH`   |
| `trending` | 热榜                | 100      | `ZHIHU_DAILY_LIMIT_TRENDING` |
| `ask`      | 直答                | 100      | `ZHIHU_DAILY_LIMIT_ASK`      |

旧统一变量 `ZHIHU_DAILY_LIMIT` 仍可用，会把三个桶同时设为同一个值（向后兼容）。

查询与清零：

```bash
uvx --from git+https://github.com/klarkxy/zhihu-search zhihu-search --quota
uvx --from git+https://github.com/klarkxy/zhihu-search zhihu-search --reset-quota
```

每次成功返回的内容末尾会附加一行配额进度：

```
配额：搜索 12/5000 · 热榜 1/100 · 直答 0/100（2026-06-19T00:00:00 刷新）
```

---

## 备选安装（pip 模式）

如果装不上 uv（老 Python、容器无网络），用 pip 源码安装：

```bash
git clone https://github.com/klarkxy/zhihu-search
cd zhihu-search
python -m pip install -e ".[dev]"
```

MCP 配置改为：

```json
{
  "mcpServers": {
    "zhihu": {
      "command": "python",
      "args": ["-m", "zhihu_search"],
      "env": {}
    }
  }
}
```

如果 venv 路径特殊，把 `command` 换成 `python -c "import sys; print(sys.executable)"` 输出的绝对路径。

项目发到 PyPI 后，`pip install zhihu-search` 可用，配置改为：

```json
{
  "mcpServers": {
    "zhihu": {
      "command": "zhihu-search",
      "args": [],
      "env": {}
    }
  }
}
```

---

## 开发者模式

```bash
git clone https://github.com/klarkxy/zhihu-search
cd zhihu-search
python -m pip install -e ".[dev]"
```

运行测试：

```bash
pytest          # 离线单元测试
pytest -v      # 详细输出
```

单元测试使用 mock，不需要真实 Access Secret。端到端探测需要先保存凭证或设置 `ZHIHU_ACCESS_SECRET`：

```bash
zhihu-search --check-token
zhihu-search --probe
```

---

## 排障

安装或配置遇到问题，先让 agent 读 [AGENT_SETUP.md](./AGENT_SETUP.md)。常见症状对应步骤：

| 症状                          | 处理位置            |
|-------------------------------|---------------------|
| `command not found: uvx`      | AGENT_SETUP 第 1 步 |
| Token 无效 / 过期             | AGENT_SETUP 第 3 步 |
| 客户端找不到工具              | AGENT_SETUP 第 5-7 步 |
| 配额显示 `剩余: 0`            | 等次日或提高上限     |

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

当前不包含缓存、客户端侧限流、多账号、系统 keyring / DPAPI 加密凭证、PyInstaller 单文件、HTTP transport 和 `tool annotations`。这些能力可以在后续需要时增量加入。

---

## 许可证

[SATA License v2.0](./LICENSE)（Star And Thank Author License）。
