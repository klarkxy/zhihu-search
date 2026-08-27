# Setup and diagnostics

Read this reference only when installing, configuring, or diagnosing `zhihu-search`, or when an
on-demand CLI request fails.

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

## Keep Codex on demand by default

For ordinary Codex use, install the Skill and let it run one narrow `uvx zhihu-search` command per
eligible task. Do not register a global stdio MCP server merely to make the Skill available: Skill
discovery is independent of MCP registration, and a long-lived Codex host may retain one stdio
server process tree per task context until the host exits.

If the current catalog already exposes matching Zhihu MCP tools, reuse them and avoid a duplicate
CLI call. Configure persistent MCP only when the user explicitly asks for high-frequency
integration and accepts the client's process lifecycle. The available profiles are `compact`,
`knowledge`, `user`, `office`, and `full`; profile names may be mixed with tool names.

## Verify without forcing the brand name

Use representative requests such as:

- `帮我查一下最近主流 RAG 评测方法在中文开发者社区的讨论，给出来源链接。`
- `真实用户怎么评价这款产品？`
- `现在大家都在讨论什么热点？`

Each positive request should produce exactly one matching core route (`search`, `ask`, or
`trending`). Also verify negative boundaries with a repository-local code question, a translation
request, and a pure math problem; those must not invoke external Zhihu capabilities.

## Install the DeepSeek Harness bundle

For DSH, use the native profile bundle instead of editing a generic MCP config or invoking a
Python-side installer:

```bash
dsh plugin --profile web add "github:klarkxy/zhihu-search"
dsh --profile web --dump-config
```

The composed config must contain one `zhihu-search-skill` row backed by
`@deepseek-ai/dsh-skill-filesystem`. Restart the target profile after a persistent install.
The Skill catalog should then include `zhihu-search`; the agent runs on-demand
`uvx zhihu-search` and must not start a persistent MCP server merely because this bundle is
installed. Keep credentials in the existing per-user Python credential file; never
add an Access Secret to the bundle, profile patch, or chat.

## Diagnose

```bash
uvx zhihu-search --quota
uvx zhihu-search --probe
uvx zhihu-search --help
codex mcp list
```

Use `codex mcp list` only to detect an unexpected persistent registration. Explain the lifecycle
cost and ask before removing or changing user configuration.

`--quota` queries Zhihu's official daily quota endpoint and does not consume business quota. It
does not read or reset any local counter. Use `quota --api-id knowledge` to narrow the result.
