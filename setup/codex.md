# Codex 配置

Codex 的默认方案是 Skill。只有高频、持续使用时才额外注册 MCP。

## 1. 安装 Skill

先完成[通用准备](README.md#准备-uvxnpx-和凭证)，然后运行：

```bash
uvx zhihu-search install-skill
```

这会通过 `npx skills` 做用户级安装，让 Skill 可跨仓库使用。只有明确需要项目
隔离时才加 `--project`。安装或更新后，新建一个 Codex 任务，让 Skill 目录
重新加载。

Skill 命中中文社区研究、真实体验、口碑、国内热点或中文来源核实时，会优先
复用当前会话已经可见的知乎 MCP；没有匹配工具时按需执行 CLI。先聚焦检索，
检查证据后按缺口补查，不因为用户说“分析/总结”就自动转交知乎直答。

## 2. 可选：注册高频 MCP

明确需要常驻集成时运行：

```bash
codex mcp add zhihu -- uvx zhihu-search serve --tools compact
codex mcp get zhihu
```

检查结果应显示服务已启用，命令为 `uvx`，参数包含
`zhihu-search serve --tools compact`。新建任务后工具才会进入新目录。

`compact` 是默认档位；知识库选 `knowledge`，用户数据选 `user`，问题发现选
`questions`，创作能力选 `creator`，PDF/PPT 选 `office`，全部 23 个 MCP
工具选 `full`。详细语义见
[MCP 高频集成](README.md#2-mcp高频集成)。不要在 MCP 配置中添加知乎凭证。

## 3. 验证

发送：

> 帮我查一下最近主流的 RAG 评测方法在中文开发者社区的讨论，返回 3 条并附来源链接。

只安装 Skill 时，应看到聚焦的按需查询，并根据结果是否充分决定补查或作答。
已经注册 MCP 时，应复用匹配工具，不通过 CLI 重复成功请求。若当前任务仍使用
旧目录，先新建任务，再考虑完整重启 Codex。

排障见[安装与配置](README.md#维护与排障)。
