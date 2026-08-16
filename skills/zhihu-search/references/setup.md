# Setup and diagnostics

Read this reference only when installing, configuring, or diagnosing `zhihu-search`, or when the
MCP-first route is unavailable.

## Install the Skill

For Codex across repositories, install globally:

```bash
uvx zhihu-search install-skill
```

This calls `npx skills` and installs globally for Codex by default, using `~/.agents/skills` as
the canonical store. Add `--project` only when the user explicitly wants project-local
`.agents/skills` isolation, or repeat `--agent <name>` to target other Agents. Start a new Codex
task after installation so the Skill catalog reloads.

## Prepare uvx and credentials

```bash
uvx --version
uvx zhihu-search --version
uvx zhihu-search --check-token
```

`--check-token` reports only configuration status and source. It must not print a secret fragment
or a user-specific credentials path. `--probe` performs one real `hot_list(limit=1)` request, so
use it only when an end-to-end upstream check is necessary.

If credentials are missing, direct the user to the Zhihu developer console and have them save the
Access Secret in their own terminal:

```bash
uvx zhihu-search --save-token "<Access Secret>"
uvx zhihu-search --probe
```

Never ask the user to paste an Access Secret, OAuth app key, or OAuth token into chat.

## Register the compact MCP server in Codex

```bash
codex mcp add zhihu -- uvx zhihu-search serve --tools compact
codex mcp get zhihu
```

Keep compact mode by default: it exposes `search`, `ask`, `trending`, and `other`. Once
registered, the Skill must prefer these MCP tools over duplicate CLI calls. If the user has Zhihu
knowledge bases and wants private-document retrieval always visible, register
`--tools knowledge` instead; also available are `user`, `office`, and `full`, and profile names
may be mixed with tool names. Run `codex mcp get zhihu` in the same target user context that
wrote the configuration and confirm `enabled: true`, `command: uvx`, and the
`zhihu-search serve --tools compact` arguments (or the chosen profile). Do not treat the add
command's success message as the only evidence. Start or reopen a Codex task so the MCP catalog
reloads; restart the client only if a fresh task still does not expose the tools.

## Verify without forcing the brand name

Use representative requests such as:

- `帮我查一下最近主流 RAG 评测方法，给出来源链接。`
- `真实用户怎么评价这款产品？`
- `现在大家都在讨论什么热点？`

Also verify negative boundaries with a repository-local code question, a translation request, and
a pure math problem; those must not invoke external Zhihu capabilities.

A compact MCP protocol handshake must expose exactly `search`, `ask`, `trending`, and `other`
before the live prompts are accepted as end-to-end proof.

## Install the DeepSeek Harness bundle

For DSH, use the native profile bundle instead of editing a generic MCP config or invoking a
Python-side installer:

```bash
dsh plugin --profile web add "github:klarkxy/zhihu-search"
dsh --profile web --dump-config
```

The composed config must contain one `zhihu-search-mcp` row backed by
`@deepseek-ai/dsh-mcp-client`, a pinned `zhihu-search` package, and `serve --tools compact`.
Restart the target profile after a persistent install. DSH exposes the initial tools as
`mcp__zhihu__search`, `mcp__zhihu__ask`, `mcp__zhihu__trending`, and
`mcp__zhihu__other`. Keep credentials in the existing per-user Python credential file; never
add an Access Secret to the bundle, profile patch, or chat.

## Diagnose

```bash
uvx zhihu-search --quota
uvx zhihu-search --probe
uvx zhihu-search --help
codex mcp list
```

Use `uvx zhihu-search --reset-quota` only for local debugging and never as routine recovery.
