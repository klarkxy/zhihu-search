# Setup and diagnostics

Read only for installation, credentials, optional MCP setup, or diagnostics. If the Skill
is already loaded and a working tool/CLI is available, return to the task; do not reinstall.

## 1. Install the Skill only when requested or absent

For Codex across repositories, use the user-level installation:

```bash
uvx --version
npx --version
uvx zhihu-search install-skill
```

Install [uv](https://docs.astral.sh/uv/) if `uvx` is missing, or
[Node.js](https://nodejs.org/) if `npx` is missing **and Skill installation is needed**.
An installed `zhihu-search` executable can run queries without `uvx` or `npx`.
Installation delegates to `npx skills` and targets Codex by default. Add `--project` only
for requested project-local isolation, or repeat `--agent <name>` for other Agents.
Reload the target client's Skill catalog; for Codex, start a new task after installation.

## 2. Prepare CLI credentials, not remote MCP credentials

Check only if CLI credential state is unknown or has changed:

```bash
uvx zhihu-search --check-token
```

`--check-token` does not make an upstream request. It must not print a secret fragment or a
user-specific credentials path. Reuse a successful check/business call in the same session.
A remote MCP server may use a different environment; a local check cannot verify it.

If missing, direct the user to the [Zhihu developer console](https://developer.zhihu.com/personal).
Have them save the Access Secret in their own terminal, not through an agent tool call:

```bash
uvx zhihu-search --save-token "<Access Secret>"
```

Never ask the user to paste an Access Secret, OAuth app key, or OAuth token into chat.
Do not read or print the credentials file. The CLI reads `ZHIHU_ACCESS_SECRET` before
its local credentials file; explain precedence without revealing values.

Only when an end-to-end connectivity check is needed:

```bash
uvx zhihu-search --probe
```

`--probe` is optional. It performs one real `hot_list(limit=1)` request, consumes one
`hot_list` call, and is neither routine preflight nor a repeated health poll. Skip it when a
business query has already succeeded, because that already verifies connectivity.

## 3. Verify behavior, not just discovery

Use a natural request such as:

> 帮我查一下最近主流 RAG 评测方法在中文开发者社区的讨论，给出来源链接。

The Skill should start with `search`, inspect the results, and return a grounded answer
with source links. Targeted follow-up searches are allowed when evidence is insufficient;
a single successful query is enough only when it covers the request. “整理/分析” should
not silently delegate the task to `ask`.

Also verify that a repository-local code question, translation, pure math, or a request to
summarize already-provided text without browsing does not invoke external Zhihu tools.

## Optional: persistent MCP for high-frequency use

Do not register a global stdio MCP server just to make the Skill available.
Skill discovery is independent of MCP registration. For occasional requests, use the
CLI on demand without a long-lived service.

Reuse matching visible MCP tools; do not duplicate successful calls through the CLI.
Configure persistent MCP only when the user explicitly asks for high-frequency integration
and accepts the client process lifecycle. Profiles are `compact`, `knowledge`, `user`,
`questions`, `creator`, `office`, and `full`; names may be mixed with explicit tool names.

```text
command: uvx
args:    zhihu-search serve --tools compact
```

In compact mode, visible `other(action="enable")` expands low-frequency tools within the
current session. Refresh/discover tools if the host supports it; do not assume the catalog
has updated. A strict allowlist cannot be expanded beyond its allowed names. Never bypass
an explicit access restriction by switching transports or changing registration.

A long-lived Codex host may retain one stdio process tree per task context until the host
exits. Explain that lifecycle before changing an existing MCP registration.

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

## Diagnose the observed failure only

Use `uvx zhihu-search <command> --help` for argument/version mismatches. Use `quota` or
`--quota` for official quota questions or a relevant `Code=30002`; it does not consume
business quota or read a local counter. Do not assume every `30002` is quota exhaustion.
For `30003` risk-control refusal, stop instead of immediately retrying.

Use `codex mcp list` only to inspect an unexpected persistent registration. Ask before
removing or changing user configuration. Do not run a blanket sequence of quota, probe,
installation, and MCP checks before an ordinary research request.
