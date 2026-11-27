# Setup and credentials

Installation, credentials, optional MCP registration, and DeepSeek Harness.

## 1. Install the Skill

User-level installation (Codex by default):

```bash
uvx --version
npx --version
uvx zhihu-search install-skill
```

`uvx` comes from [uv](https://docs.astral.sh/uv/); `npx` from [Node.js](https://nodejs.org/)
and is needed only for Skill installation. An installed `zhihu-search` executable runs
queries without `uvx` or `npx`. Installation delegates to `npx skills`. `--project` installs
project-locally; repeat `--agent <name>` for other Agents; `--copy` copies instead of linking.
Clients load new Skills after reloading their Skill catalog (for Codex, a new task).

## 2. CLI credentials

```bash
uvx zhihu-search --check-token
```

`--check-token` makes no upstream request. It must not print a secret fragment or a
user-specific credentials path. A remote MCP server may run in a different environment; a
local check says nothing about it.

The Access Secret comes from the [Zhihu developer console](https://developer.zhihu.com/personal)
and is saved by the user in their own terminal:

```bash
uvx zhihu-search --save-token "<Access Secret>"
```

Access Secrets, OAuth app keys, and OAuth tokens are never pasted into chat, and the
credentials file is never read or printed. `ZHIHU_ACCESS_SECRET` takes precedence over the
local credentials file. `--clear-token` removes the saved secret.

Publishing uses a separate pair, `ZHIHU_OPENAPI_APP_KEY` and `ZHIHU_OPENAPI_APP_SECRET`,
from <https://www.zhihu.com/playground/zhihu-sync>. Save the authorization text in the
user's terminal, not in chat:

```bash
uvx zhihu-search --save-openapi "<授权说明全文>"
uvx zhihu-search --check-openapi
```

`--check-openapi` reports the source and App Key. It must not print the App Secret.
Profile `sync` exposes the publish tools; `compact` does not. See [sync](sync.md).

```bash
uvx zhihu-search --probe
```

`--probe` performs one real `hot_list(limit=1)` request and consumes one `hot_list` call.

## Optional: persistent MCP for high-frequency use

Do not register a global stdio MCP server just to make the Skill available.
Skill discovery is independent of MCP registration; the CLI works on demand without a
long-lived service. Configure persistent MCP only when the user explicitly asks for
high-frequency integration and accepts the client process lifecycle. Profiles are `compact`,
`knowledge`, `user`, `questions`, `creator`, `office`, and `full`; names may be mixed with
explicit tool names.

```text
command: uvx
args:    zhihu-search serve --tools compact
```

In compact mode, `other(action="enable")` registers low-frequency tools for the current
session; hosts that cache the catalog need a refresh. A strict allowlist cannot be expanded
beyond its allowed names.

A long-lived Codex host may retain one stdio process tree per task context until the host
exits. `codex mcp list` shows current registrations.

## DeepSeek Harness

This repository no longer ships a DSH plugin. Install the maintained package:

```bash
dsh plugin --profile web add @klarkxy/dsh-zhihu
```

Source and usage: <https://github.com/klarkxy/dsh-plugins/tree/main/plugins/dsh-zhihu>

If the profile still has the old `dsh-plugin-zhihu-search` package, remove it after the new
plugin is installed:

```bash
dsh plugin --profile web remove dsh-plugin-zhihu-search
```

Enter the Access Secret in the plugin settings (`ZHIHU_ACCESS_TOKEN`). Never add it to a profile
patch or to chat.

## 调用与费用保护

默认是免费保护模式：业务请求按对应的知乎官方免费额度分组预查；额度充足（剩余不少于 20）时，同一分组最多每 5 分钟重新查询一次，额度接近耗尽或无法确认时则每次请求前查询。预查失败、缺少有效额度、额度不足或映射未确认时，不发送业务请求。

本地北京时间每日上限默认 **1000 次**，可设为 1–100000；计数包含已发送后失败、取消或结果未知的请求。进程内会短时间复用相同的搜索、全网搜索、热榜和问题回答结果（约 5–10 分钟），命中复用结果不再消耗额度。

两个客户端共用保护状态；`ZHIHU_SEARCH_HOME` 可改变根目录，`ZHIHU_CALL_POLICY_DIR` 可显式指定共同保护目录。保护锁只覆盖本地账本的预留与结算，业务请求可以并发执行；进程崩溃留下的锁约 60 秒后会自动恢复。

显式付费模式可用 `ZHIHU_ALLOW_PAID=true` 开启；`ZHIHU_DAILY_CALL_LIMIT` 调整每日上限。CLI 也可以传 `--allow-paid` 和 `--daily-call-limit`（放在子命令前），MCP/OpenAPI 通过启动环境配置。未确认计费规则的能力即使开启付费模式也会保守拒绝。

本地保护**不能承诺绝对零费用**：同账号其他客户端可能在预查后竞争免费额度，平台扣费时间也不由本机控制。结果未知时先在官方控制台核对，不盲目重试。官方依据：[服务价格](https://developer.zhihu.com/docs?key=billing_price)、[免费额度](https://developer.zhihu.com/docs?key=quota)、[线上订购协议](https://developer.zhihu.com/content/order-agreement)。API 计费不扩大内容访问或传播授权范围。
