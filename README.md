# zhihu-search

知乎开放平台的统一 CLI + MCP + OpenAPI + Skill 封装。**一个入口**覆盖搜索、直答和热榜，支持四种使用方式：

- **CLI** → 终端直接搜索、提问、查看热榜（不需要任何 AI 客户端）
- **MCP** → 以 stdio MCP 服务器方式暴露 `search`、`ask`、`trending` 三个工具给 AI 编程助手调用
- **OpenAPI** → 以 HTTP OpenAPI 工具服务器方式接入 Open WebUI
- **Skill** → 以 skills.sh 标准 skill 引导 agent 直接调用 CLI 完成知乎查询

---

## 快速开始

### CLI 直用（零配置）

```bash
pip install zhihu-search

# 保存凭证
zhihu-search --save-token "zh-your-secret"

# 搜索
zhihu-search search "RAG 评测方法" --scope zhihu --count 5

# 直答
zhihu-search ask "什么是多模态大模型？" --model thinking

# 热榜
zhihu-search trending --limit 10

# JSON 输出（脚本消费）
zhihu-search search "大模型" --format json
```

### MCP 模式（AI 编程助手）

```bash
zhihu-search serve
```

在你的 MCP 客户端配置中注册：

```json
{
  "mcpServers": {
    "zhihu-search": {
      "command": "zhihu-search",
      "args": ["serve"]
    }
  }
}
```

然后 agent 就能调用 `search`、`ask`、`trending` 三个工具。

各客户端详细配置见：

| 客户端 | 指南 |
|---|---|
| Claude Code | [setup/claude-code.md](setup/claude-code.md) |
| Codex | [setup/codex.md](setup/codex.md) |
| HanaAgent | [setup/hanako-agent.md](setup/hanako-agent.md) |
| OpenCode | [setup/opencode.md](setup/opencode.md) |
| 通用 | [setup/SETUP.md](setup/SETUP.md) |

### Open WebUI / OpenAPI 模式

```bash
zhihu-search openwebui --host 0.0.0.0 --port 8000 --api-key "<bearer-token>"
```

Open WebUI 中添加 External Tool Server：

- URL: `http://<server>:8000`
- Authentication: Bearer token

OpenAPI schema 会声明标准 HTTP Bearer 认证，工具接口为 `search`、`ask`、`trending`。

### 让 AI 直接用 CLI 查

安装好并保存凭证后，复制这段 prompt 给支持 skills 的 AI 编程助手：

> 用 zhihu-search skill 搜一下知乎上关于「RAG 评测方法」的高质量内容，总结前 5 条并附链接。

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

本项目把这 4 个接口封装成 4 种接入方式：

| 方式 | 入口 | 适用场景 |
|---|---|---|
| **CLI** | `zhihu-search search/ask/trending` | 终端、脚本、CI |
| **MCP** | `zhihu-search serve` | AI 编程助手持续调用 |
| **OpenAPI** | `zhihu-search openwebui` | Open WebUI 外部工具服务器 |
| **Skill** | `skills/zhihu-search/SKILL.md` | Agent 按任务直接调用 CLI |

不做缓存、客户端侧限流、多账号——保持简单，行为贴近知乎官方接口。

---

## CLI 参考

### `zhihu-search search <query>`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `query` | `str` | 必填 | 搜索关键词，2-100 字符 |
| `--scope` | `zhihu\|web` | `zhihu` | `zhihu` 站内搜索；`web` 全网搜索 |
| `--count` | `int` | `10` | 返回条数；zhihu 上限 10，web 上限 20 |
| `--filter` | `str` | `""` | 仅 `scope=web` 生效，例如 `host=="example.com"` |
| `--format` | `markdown\|json` | `markdown` | 输出格式；json 时 stdout 只有 JSON |

### `zhihu-search ask <query>`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `query` | `str` | 必填 | 问题 |
| `--model` | `fast\|thinking\|agent` | `fast` | 模型档位 |
| `--format` | `markdown\|json` | `markdown` | 输出格式 |

### `zhihu-search trending`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `--limit` | `int` | `30` | 返回条数，上限 30 |
| `--format` | `markdown\|json` | `markdown` | 输出格式 |

### `zhihu-search openwebui`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `--host` | `str` | `127.0.0.1` | 监听地址 |
| `--port` | `int` | `8000` | 监听端口 |
| `--api-key` | `str` | 空 | 设置后要求 `Authorization: Bearer <token>` |

---

## MCP 工具参考

### `search(query, scope="zhihu"|"web", count=10, filter="")`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `query` | `str` | 必填 | 搜索关键词，2-100 字符 |
| `scope` | `"zhihu"\|"web"` | `"zhihu"` | `zhihu` 站内搜索；`web` 全网搜索 |
| `count` | `int` | `10` | 返回条数；zhihu 上限 10，web 上限 20 |
| `filter` | `str` | `""` | 仅 `scope="web"` 生效，例如 `host=="example.com"` |

返回 Markdown：标题、链接、作者、权威等级、赞同数、评论数、摘要。

### `ask(query, model="fast"|"thinking"|"agent")`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `query` | `str` | 必填 | 问题 |
| `model` | `"fast"\|"thinking"\|"agent"` | `"fast"` | 模型档位 |

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

## 熔断保护（Circuit Breaker）

不同账号在知乎开放平台的额度不同，硬编码上限没有参考价值。本项目采用**熔断机制**：当某个接口返回限流错误（HTTP 429 或 `Code=30001`）时，熔断器开始计数。连续 `2` 次限流后，该接口自动熔断，所有请求立即失败并提示冷却剩余时间，**约 6 小时后**自动恢复（半开试探）。

熔断状态按接口类别独立维护：

| 类别 | 包含接口 | 熔断阈值 | 冷却时间 |
|---|---|---|---|
| `search` | 知乎搜索 / 全网搜索 | 连续 2 次限流 | 6 小时 |
| `trending` | 热榜 | 连续 2 次限流 | 6 小时 |
| `ask` | 直答 | 连续 2 次限流 | 6 小时 |

熔断器状态会在每次调用末尾提示。正常时：

```
今日调用：搜索 12 · 热榜 1 · 直答 0
```

熔断时：

```
今日调用：搜索 12 · 热榜 1 · 直答 0
⚠ 搜索已熔断（冷却剩余 95 秒）
```

使用 `zhihu-search --quota` 查看全部状态：

```
今日调用：搜索 12 · 热榜 1 · 直答 0

今日调用量：
  搜索  12 次
  热榜  1 次
  直答  0 次

熔断状态：
  搜索  正常
  热榜  已熔断（冷却剩余 95 秒）
  直答  正常
```

使用 `zhihu-search --reset-quota` 可手动清零计数并重置所有熔断器。

---

## 开发者模式

```bash
git clone https://github.com/klarkxy/zhihu-search
cd zhihu-search
python -m pip install -e ".[dev]"
```

```bash
pytest                    # 离线单元测试
pytest -v                 # 详细输出
zhihu-search --check-token   # 凭证检查
zhihu-search --probe         # 端到端探测
```

---

## 排障

| 症状 | 处理位置 |
|---|---|
| `command not found: zhihu-search` | `pip install zhihu-search` |
| Token 无效 / 过期 | [setup/SETUP.md](setup/SETUP.md) |
| 客户端找不到工具 | 对应客户端的 setup/*.md |
| CLI 报「凭证错误」 | `zhihu-search --save-token` |
| 配额显示 `剩余: 0` | 等次日或提高上限 |

---

## 架构

```
┌─ CLI ─────────────────────┐
│  zhihu-search search ...   │
│  zhihu-search ask ...      │  ───   commands.py（业务层）
│  zhihu-search trending ... │         formatters.py（格式化层）
└────────────────────────────┘         http_client.py（HTTP）
                                         credentials.py
┌─ MCP ─────────────────────┐              quota.py
│  AI 编程助手               │
│    → server.py（FastMCP）  │  ───   developer.zhihu.com
│    → search / ask / trendy │        （Bearer + X-Request-Timestamp）
└────────────────────────────┘

┌─ OpenAPI ─────────────────┐
│  Open WebUI                │
│    → openwebui.py          │  ───   developer.zhihu.com
│    → /search /ask /trending│
└────────────────────────────┘

┌─ Skill ────────────────────┐
│  skills/zhihu-search/       │  ───   Agent 直接调用 CLI
│    SKILL.md                 │
│  skills.sh.json             │
└─────────────────────────────┘
```

HTTP REST 比 SSE 简单：每个请求独立，无长连接、无重连逻辑。CLI/MCP 共享同一套业务层（`commands.py`）和格式化层（`formatters.py`）。

---

## 当前边界

不包含缓存、客户端侧限流、多账号、系统 keyring / DPAPI 加密凭证、PyInstaller 单文件、HTTP transport 和 `tool annotations`。后续按需增量加入。

---

## 许可证

[SATA License v2.0](LICENSE)（Star And Thank Author License）。
