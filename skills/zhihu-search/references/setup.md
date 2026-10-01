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
