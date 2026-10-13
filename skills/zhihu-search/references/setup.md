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


## 调用与费用保护（2026-10-13）

默认是免费保护模式：每个业务请求先即时查询对应的官方免费额度；查询失败、缺少有效额度、额度不足或映射未确认时，不发送业务请求。额度查询本身不递归预查、不消耗本地上限。工具名及业务路径保持原样；旧额度输入 `question_answers` 映射为 `question_discovery`，问题推荐和回答摘要共用该组。

本地北京时间每日上限默认 **100 次**，可设为 1–100000。计数口径是已持久化预留的业务请求：包括已发送后失败、取消或结果未知的请求；预查失败不占用上限。它与官方免费次数、已有本地工具使用统计、钱包和账单分别处理，不估算费用或余额。

免费模式可使用有可靠额度映射的 fast/thinking 直答、问题推荐以及 PDF/PPT 任务；缺少单价不影响使用已确认的免费额度。显式付费模式对未确认计费的能力保守拒绝，并提示切换回免费保护模式。通用资源文件上传尚无可靠额度映射，暂时阻止；知识库上传的 `knowledge` 映射已确认。

两个客户端共用 `~/.config/zhihu-search/call-policy/daily.json` 和 `request.lock`；`ZHIHU_SEARCH_HOME` 可改变根目录，`ZHIHU_CALL_POLICY_DIR` 可显式指定共同保护目录。同目录内所有账号/进程共用一个本地上限，避免多 Secret 或多入口绕开计数；自定义目录时需让两项目使用同一路径。锁覆盖预查与请求，状态先原子预留，不缓存额度、不自动重试。网络失败或取消后的未知请求保守占用对应免费容量，跨日仍保留这些未知预留。

本地保护**不能承诺绝对零费用**：同账号其他客户端可能在预查后竞争免费额度，平台扣费时间也不由本机控制。结果未知时先在官方控制台核对，不盲目重试。进程崩溃留下的锁不会自动抢占；确认两个客户端均无在途请求、核对未知请求后才可手动移除 `request.lock`。损坏的计数文件会失败关闭，不自动清零。

鉴权和账号设置保持不变。不提供充值、权益兑换或钱包查询。官方依据：[服务价格](https://developer.zhihu.com/docs?key=billing_price)、[免费额度](https://developer.zhihu.com/docs?key=quota)、[线上订购协议](https://developer.zhihu.com/content/order-agreement)（V1.0，2026-10-10 生效）。API 计费不扩大内容访问或传播授权范围。


### CLI、MCP 与 OpenAPI 配置

默认无需新配置。环境变量 `ZHIHU_ALLOW_PAID=true` 显式允许已确认计费能力付费续用，`ZHIHU_DAILY_CALL_LIMIT=200` 调整每日上限；未设置时分别为 false 和 100。CLI 全局参数也可用于本次进程：

```bash
zhihu-search --daily-call-limit 50 search "普通资料"
zhihu-search --allow-paid --daily-call-limit 50 search "普通资料"
```

参数需放在子命令前。MCP/OpenAPI 服务通过启动环境配置这些选项，模型工具参数不能改变付费开关。门禁在共享 REST 调用层，涵盖 GET、POST、知识库上传、直答和任务请求。

官方额度更新也可能滞后：免费模式每次仍查询官方值，同时保留本机已消耗预留的容量上限，取更保守的值，不在当天自动补回；这个内部上限不会作为官方余额展示。次日按北京时间重置，结果未知的预留仍保留。
