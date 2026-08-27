# Setup and diagnostics

Read this reference only when the Skill needs installation, credentials, optional MCP setup, or
diagnostics. For ordinary research, return to `SKILL.md` and use one matching route.

## 1. Install the Skill

For Codex across repositories, use the user-level installation:

```bash
uvx --version
npx --version
uvx zhihu-search install-skill
```

Install [uv](https://docs.astral.sh/uv/) if `uvx` is missing, or
[Node.js](https://nodejs.org/) if `npx` is missing. This delegates installation to `npx skills`
and targets Codex by default. Add `--project` only
when the user explicitly wants project-local isolation, or repeat `--agent <name>` for other
Agents. Start a new Codex task after installation so the Skill catalog reloads.

## 2. Prepare credentials

```bash
uvx --version
uvx zhihu-search --version
uvx zhihu-search --check-token
```

`--check-token` does not make an upstream request. It must not print a secret fragment or a
user-specific credentials path. If credentials are missing, direct the user to the Zhihu
developer console and have them save the Access Secret in their own terminal:

```bash
uvx zhihu-search --save-token "<Access Secret>"
uvx zhihu-search --probe
```

`--probe` performs one real `hot_list(limit=1)` request. Use it only for an end-to-end check, not
as a repeated health poll. Never ask the user to paste an Access Secret, OAuth app key, or OAuth
token into chat.

## 3. Verify the Skill

Use a natural request such as:

> 帮我查一下最近主流 RAG 评测方法在中文开发者社区的讨论，给出来源链接。

The Skill should be discovered, choose exactly one matching core route, and return a useful result
with source links. Also check the negative boundary with a repository-local code question, a
translation request, or a pure math problem; those must not invoke external Zhihu capabilities.

## Optional: persistent MCP for high-frequency use

Do not register a global stdio MCP server just to make the Skill available. Skill discovery is
independent of MCP registration. For occasional requests, keep using the Skill with one on-demand
CLI command.

If matching Zhihu MCP tools are already visible, reuse them and do not duplicate the request with
the CLI. Configure persistent MCP only when the user explicitly asks for high-frequency integration
and accepts the client process lifecycle. The profiles are `compact`, `knowledge`, `user`,
`office`, and `full`; profile names may be mixed with explicit tool names.

```text
command: uvx
args:    zhihu-search serve --tools compact
```

A long-lived Codex host may retain one stdio process tree per task context until the host exits.
Explain that lifecycle before changing an existing MCP registration.

## DeepSeek Harness: install the same Skill

For DSH, use the native profile bundle instead of editing a generic MCP config:

```bash
dsh plugin --profile web add "github:klarkxy/zhihu-search"
dsh --profile web --dump-config
```

The composed config must contain one `zhihu-search-skill` row backed by
`@deepseek-ai/dsh-skill-filesystem`. Restart the target profile after a persistent install, then
verify that the Skill appears and performs one real query. The bundle must not start a persistent MCP server.
Keep credentials in the existing per-user Python credential file; never
add an Access Secret to the bundle, profile patch, or chat.

## Diagnose

```bash
uvx zhihu-search --quota
uvx zhihu-search --probe
uvx zhihu-search --help
codex mcp list
```

Use `codex mcp list` only to detect an unexpected persistent registration. Ask before removing or
changing user configuration. `--quota` queries Zhihu's official daily quota and does not consume
business quota or read a local counter.
