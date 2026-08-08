# Codex 配置

先完成 [通用准备](README.md)。

## 全局安装 Skill

```bash
npx skills add klarkxy/zhihu-search --skill zhihu-search -g -a codex -y
```

`-g` 让 Skill 在所有仓库中可用。只有明确需要项目隔离时才去掉 `-g`。
安装后重新打开 Codex 任务，让 Skill 目录重新加载。

## 配置 MCP

推荐直接执行：

```bash
codex mcp add zhihu -- uvx zhihu-search serve --tools compact
```

也可以手动在 `~/.codex/config.toml` 中加入：

```toml
[mcp_servers.zhihu]
command = "uvx"
args = ["zhihu-search", "serve", "--tools", "compact"]
```

保留文件中已有的其他配置，不要把 Access Secret 或 OAuth token 写进这里。
如需一次暴露全部 13 个工具，将 `compact` 改为 `full`；其他开关见
[通用安装说明](README.md#3-配置-mcp高频使用)。

Skill 与 MCP 同时可用时，Skill 优先调用 `search`、`ask`、`trending`；只有
MCP 不可用时才回退 `uvx`。

## 重启

关闭并重新打开 Codex。

## 验证

发送：

> 帮我查一下最近主流的 RAG 评测方法，返回 3 条结果并附来源链接。

再分别验证：

> 真实用户怎么评价这款产品？

> 现在大家都在讨论什么热点？

如果工具没有出现或调用失败，查看 [通用排障](README.md#通用排障)。
