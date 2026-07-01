---
name: zhihu-search
description: 知乎开放平台 CLI + MCP 集成：搜索、直答、热榜，支持命令行与 Agent 双模式接入
tip: |
  提供三种使用方式：
  - CLI 直用：`zhihu-search search "问题"` → 终端直接看结果
  - MCP 模式：配置 `zhihu-search serve` 暴露工具给 AI 编程助手
  - Skill 模式：本 skill 教会 agent 安装、配置、选模式
---

# zhihu-search

知乎开放平台（developer.zhihu.com）的 CLI + MCP 封装。一个入口覆盖搜索、直答和热榜。

## 安装

```bash
pip install zhihu-search
```

或从源码安装（开发者模式）：

```bash
git clone https://github.com/klarkxy/zhihu-search
cd zhihu-search
pip install -e ".[dev]"
```

## 凭证

需要先获取知乎开放平台 Access Secret（[开发者后台](https://developer.zhihu.com) → 应用管理 → 创建应用 → 复制 Access Secret）。

保存方式（二选一）：

```bash
# 方式 A：环境变量（推荐 CI / Docker）
export ZHIHU_ACCESS_SECRET="zh-your-secret"

# 方式 B：持久化到文件
zhihu-search --save-token "zh-your-secret"
```

**安全警告**：Access Secret 等同密码。不要写入聊天记录、`.mcp.json`、截图或公开仓库。

## 用法

### 方式 1：CLI 直用（不需要任何 MCP 客户端）

```bash
# 搜索
zhihu-search search "RAG 评测方法" --scope zhihu --count 5

# 全网搜索 + 高级筛选
zhihu-search search "AI 论文" --scope web --count 10 --filter 'host=="arxiv.org"'

# 直答
zhihu-search ask "什么是多模态大模型？" --model thinking

# 热榜
zhihu-search trending --limit 10

# JSON 输出（脚本消费）
zhihu-search search "大模型" --format json
```

### 方式 2：MCP 服务器（AI 编程助手调用）

```bash
zhihu-search serve
```

在 MCP 客户端（Claude Code / Cursor / Codex）的配置文件中注册：

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

MCP 暴露三个工具：

| 工具 | 功能 | 参数 |
|---|---|---|
| `search` | 知乎/全网搜索 | `query`, `scope`(zhihu/web), `count`, `filter` |
| `ask` | 知乎直答 | `query`, `model`(fast/thinking/agent) |
| `trending` | 知乎热榜 | `limit` |

### 方式 3：本 Skill（Agent 引导式安装）

Agent 读取本 skill 后，应：

1. 检查 Python 是否已安装 → 没有则引导安装
2. 安装 `zhihu-search` 包 → `pip install zhihu-search`
3. 检查凭证 → `zhihu-search --check-token`
4. 若未配置凭证 → 引导用户从[开发者后台](https://developer.zhihu.com)获取，然后用 `--save-token` 保存
5. 判断接入模式：
   - 如果用户只是想快速查一个资料 → 用 CLI 模式（`zhihu-search search ...`）
   - 如果用户要持续使用 → 配置 MCP 并注册到客户端
6. 端到端验证 → `zhihu-search --probe`

## 诊断

```bash
# 检查凭证
zhihu-search --check-token

# 查看今日调用量与熔断状态
zhihu-search --quota

# 手动重置熔断器与计数
zhihu-search --reset-quota

# 端到端探测
zhihu-search --probe

# 帮助
zhihu-search --help
zhihu-search search --help
```

> **熔断机制**：当某个接口被限流（连续 2 次）后，熔断器自动开启，冷却约 6 小时后试探恢复。状态通过 `--quota` 查看，或用 `--reset-quota` 手动复位。

## 详细文档

- [README.md](https://github.com/klarkxy/zhihu-search)
- [AGENT_SETUP.md](https://github.com/klarkxy/zhihu-search/blob/main/AGENT_SETUP.md)
- [开发者后台](https://developer.zhihu.com)
