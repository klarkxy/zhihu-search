# zhihu-search

用一个命令调用知乎开放平台：搜索、直答、热榜、用户公开数据、知识库、
PDF 解析、PPT 生成和 OAuth 辅助流程。

推荐按下面的顺序选择入口：

| 顺序 | 方式 | 适合场景 |
|---:|---|---|
| 1 | **DSH 插件** | DeepSeek Harness 用户；安装一个 profile bundle |
| 2 | **Skill** | 其他 Agent；主动识别任务，优先 MCP、回退 CLI |
| 3 | **CLI** | 临时查询、脚本和调试 |
| 4 | **MCP** | 在 AI 客户端中高频、持续调用 |
| 5 | **OpenWebUI** | 少数需要 HTTP 工具服务器的场景 |

## 1. DeepSeek Harness 插件

DSH 用户直接安装声明式 bundle；Python CLI 不负责修改 DSH 配置：

```bash
dsh plugin --profile web add "github:klarkxy/zhihu-search"
```

插件使用 DSH 自带的 MCP client，通过 `uvx` 启动与插件版本一致的
`zhihu-search`，默认注册 `mcp__zhihu__search`、`mcp__zhihu__ask`、
`mcp__zhihu__trending` 和 `mcp__zhihu__other` 四个 compact 工具。
Access Secret 仍由 Python 的用户级凭证文件
读取，不进入 DSH 配置。安装、验证、更新和移除见
[DSH 指南](setup/dsh.md)。

## 2. Skill（推荐）

安装 Skill：

```bash
uvx zhihu-search install-skill
```

该命令调用官方 `npx skills`，默认把 Skill 全局安装给 Codex。skills CLI
会以 `~/.agents/skills` 作为统一来源，并为目标 Agent 建立所需入口。只有明确
需要项目隔离时才使用 `uvx zhihu-search install-skill --project`，安装到当前
项目的 `.agents/skills`。也可重复传入 `--agent`，例如：

```bash
uvx zhihu-search install-skill --agent codex --agent claude-code
```

需要直接调用底层命令时，等价命令为：

```bash
npx skills add klarkxy/zhihu-search --skill zhihu-search -g -a codex -y
```

具体范围规则见 [skills CLI 安装范围](https://github.com/vercel-labs/skills#installation-scope)。
Skill 在已注册 `zhihu` MCP 时优先调用 `search`、`ask`、`trending`，
MCP 不可用时才回退 `uvx zhihu-search`。因此本机还需安装
[uv](https://docs.astral.sh/uv/getting-started/installation/)。`uvx` 会按需
创建隔离环境，无需长期安装 Python 包。

首次使用只需在自己的终端保存并验证 Access Secret：

```bash
uvx zhihu-search --save-token "<你的 Access Secret>"
uvx zhihu-search --probe
```

Access Secret 在
[知乎开放平台个人中心](https://developer.zhihu.com/personal)创建。不要把它
发到聊天、截图或仓库。

## 3. CLI

不需要 Agent 时，直接用 `uvx`：

```bash
uvx zhihu-search search "RAG 评测方法" --count 5
uvx zhihu-search ask "什么是 ReAct Agent？" --model thinking
uvx zhihu-search trending --limit 10
```

用户数据、知识库、PDF、PPT 和 OAuth 也都可以从 CLI 调用：

```bash
uvx zhihu-search user-contents --content-type article --limit 10
uvx zhihu-search knowledge-bases --scope all
uvx zhihu-search knowledge-search "退款规则" --recall-scope personal
uvx zhihu-search pdf-upload "./report.pdf"
uvx zhihu-search pdf-create "file_..."
uvx zhihu-search ppt-create "https://zhuanlan.zhihu.com/p/123" --pages 12
uvx zhihu-search oauth-url "<app_id>" "<redirect_uri>"
```

所有业务命令支持 `--format json`。完整参数见：

```bash
uvx zhihu-search --help
uvx zhihu-search <command> --help
```

在仓库目录验证尚未发布的代码时，把命令开头改为
`uvx --from . zhihu-search`。

## 4. MCP（高频集成）

MCP 默认使用 `compact`，只暴露三个常用工具和一个按需入口：

Codex 的普通、低频查询应安装 Skill 后按需运行 CLI，不需要全局注册 MCP。
只有用户明确要求高频常驻集成，并接受客户端的进程生命周期时才配置 MCP。
Codex 专用说明见 [setup/codex.md](setup/codex.md)。其他 MCP 客户端可启动：

```text
command: uvx
args:    zhihu-search serve --tools compact
```

| 档位 | 暴露内容 |
|---|---|
| `compact`（默认） | `search`、`ask`、`trending`、`other` |
| `knowledge` | compact 加 3 个知识库工具 |
| `user` | compact 加 5 个用户数据工具 |
| `office` | compact 加 2 个 PDF 和 2 个 PPT 工具 |
| `full` | 全部 16 个工具 |

档位和工具名可以逗号混写，结果取并集，例如 `knowledge,user` 或
`compact,knowledge_search`。只写工具名则是严格 allowlist，例如
`search,ask,pdf_status`。

`other` 管理当前 MCP 会话中的低频工具：

- `enable`：展开 5 个用户数据工具、3 个知识库工具、2 个 PDF 工具和 2 个 PPT 工具。
- `disable`：收起这 12 个工具。
- `reset`：恢复启动时的工具集合。

只要选择里出现档位名，`other` 就能管理全部 12 个低频工具；纯工具名的严格
allowlist 下，它只能管理列表里已经允许的低频工具，不能越过开关。

也可以用 `ZHIHU_MCP_TOOLS` 设置默认配置；命令行 `--tools` 优先于环境
变量。常用写法：

```bash
uvx zhihu-search serve --tools knowledge   # 自建知识库检索常驻可见
uvx zhihu-search serve --tools full        # 一次暴露全部显式工具
```

通用 JSON 配置：

```json
{
  "mcpServers": {
    "zhihu": {
      "command": "uvx",
      "args": ["zhihu-search", "serve", "--tools", "compact"]
    }
  }
}
```

注册 MCP 后，`zhihu-search` Skill 会优先使用这三个核心工具，避免重复执行
同一条 CLI 查询。

客户端指南：

- [Codex](setup/codex.md)
- [Claude Code](setup/claude-code.md)
- [OpenCode](setup/opencode.md)
- [HanaAgent](setup/hanako-agent.md)

PDF / 知识库本机上传和 OAuth token 交换仍只允许 CLI/Python 执行，不会
成为模型可调用的工具。

## 5. OpenWebUI（少数场景）

只有需要 HTTP OpenAPI 工具服务器时才使用：

```bash
uvx zhihu-search openwebui \
  --host 0.0.0.0 --port 8000 --api-key "<服务访问口令>"
```

在 Open WebUI 中添加 External Tool Server：

- URL：`http://<server>:8000`
- Authentication：Bearer token

也可用 `ZHIHU_OPENWEBUI_API_KEY` 设置访问口令。未配置口令时服务不做
入站认证，只能用于 localhost 或受控私网。

更完整的安装说明见 [setup/README.md](setup/README.md)。

## 能力覆盖

| 能力 | 端点数 | 说明 |
|---|---:|---|
| 搜索、直答、热榜 | 4 | 知乎搜索、全网搜索、直答、热榜 |
| 用户公开数据 | 5 | 创作、关注、近期收藏和收藏夹 |
| 知识库 | 4 | 列表、内容、上传、检索 |
| PDF 解析 | 3 | 上传、创建任务、查询状态 |
| PPT 生成 | 2 | 创建任务、查询状态 |
| OAuth 辅助 | 2 | 授权 URL、授权码换 token |

逐端点说明、官方文档差异和安全边界见
[API_COVERAGE.md](docs/API_COVERAGE.md)。

## 凭证与诊断

Access Secret 读取顺序：

1. `ZHIHU_ACCESS_SECRET`
2. `~/.config/zhihu-search/credentials.json`

```bash
uvx zhihu-search --check-token
uvx zhihu-search --probe
uvx zhihu-search --quota
uvx zhihu-search --clear-token
```

`--check-token` 只报告是否已配置及凭证来源，不输出 Secret 片段或本机凭证
路径；`--probe` 会真实调用一次 `hot_list(limit=1)` 并消耗一次请求额度。

常见问题：

| 现象 | 处理 |
|---|---|
| 找不到 `uvx` | 安装 uv 后重开终端 |
| 凭证不存在或失效 | 回个人中心创建并重新保存 Access Secret |
| `Code=30002` | 到知乎开发者后台检查额度或接口权限 |
| MCP 工具未出现 | 检查配置后重启客户端 |
| PDF/PPT 长时间处理中 | 稍后再查状态，不要紧密轮询 |
| 知识库列表为空 | 先登录 [直答知识库](https://zhida.zhihu.com/repositories/square) 完成初始化 |

Agent 代为安装和验证时，参见 [AGENT_SETUP.md](AGENT_SETUP.md)。

## 开发

```bash
git clone https://github.com/klarkxy/zhihu-search
cd zhihu-search
uv sync --extra dev
uv run pytest
uv build
```

## 许可证

[SATA License v2.0](LICENSE)
