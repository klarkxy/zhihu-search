# Codex 配置

先完成 [通用准备](README.md)。

## 全局安装 Skill

```bash
uvx zhihu-search install-skill
```

该命令内部调用 `npx skills`，并以 `~/.agents/skills` 为统一来源，让 Skill
在所有仓库中可用。只有明确需要项目隔离时才加 `--project`。
安装后重新打开 Codex 任务，让 Skill 目录重新加载。

## 默认按需调用

普通 Codex 使用只需要安装 Skill。命中中文社区研究、真实体验、口碑、国内热点
或中文来源核实时，Skill 会按需执行一条最窄的 CLI 命令：

```bash
uvx zhihu-search search "<query>" --scope zhihu --count 5
uvx zhihu-search ask "<question>" --model fast
uvx zhihu-search trending --limit 10
```

Skill 的发现与 MCP 注册相互独立。不要为了偶尔查询而把 stdio MCP 全局注册到
Codex；长时间运行的宿主可能按任务上下文保留多套服务进程，直到宿主退出。

## 可选的高频 MCP 集成

只有用户明确要求高频、常驻集成，并接受目标客户端的进程生命周期时才配置
MCP。`compact` 暴露 `search`、`ask`、`trending`、`other`；知识库用
`knowledge`，用户数据用 `user`，PDF/PPT 用 `office`，全部工具用 `full`。
完整服务端开关见 [通用安装说明](README.md#4-mcp高频集成)。当前目录已经
暴露匹配 MCP 工具时，Skill 会直接复用，不再重复执行 CLI。

## 重启

安装或更新 Skill 后新建任务。目录仍是旧版本时，再完整退出并重新打开 Codex
客户端；当前任务不会热更新已经加载的 Skill 指令。

## 验证

发送以下正例，并确认每条只走一条匹配的 `search`、`ask` 或 `trending` 路由：

> 帮我查一下最近主流的 RAG 评测方法在中文开发者社区的讨论，返回 3 条结果并附来源链接。

再分别验证：

> 真实用户怎么评价这款产品？

> 现在大家都在讨论什么热点？

如果工具没有出现或调用失败，查看 [通用排障](README.md#维护与排障)。
