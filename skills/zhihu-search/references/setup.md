# Setup and diagnostics

Read this reference only when installing, configuring, or diagnosing `zhihu-search`, or when the
MCP-first route is unavailable.

## Install the Skill

For Codex across repositories, install globally:

```bash
npx skills add klarkxy/zhihu-search --skill zhihu-search -g -a codex -y
```

Omit `-g` only when the user explicitly wants an isolated project-level installation. Start a new
Codex task after installation so the Skill catalog reloads.

## Prepare uvx and credentials

```bash
uvx --version
uvx zhihu-search --check-token
```

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
```

Keep compact mode: it exposes `search`, `ask`, `trending`, and `other`. Once registered, the Skill
must prefer these MCP tools over duplicate CLI calls. Restart Codex after changing MCP config.

## Verify without forcing the brand name

Use representative requests such as:

- `帮我查一下最近主流 RAG 评测方法，给出来源链接。`
- `真实用户怎么评价这款产品？`
- `现在大家都在讨论什么热点？`

Also verify negative boundaries with a repository-local code question, a translation request, and
a pure math problem; those must not invoke external Zhihu capabilities.

## Diagnose

```bash
uvx zhihu-search --quota
uvx zhihu-search --probe
uvx zhihu-search --help
codex mcp list
```

Use `uvx zhihu-search --reset-quota` only for local debugging and never as routine recovery.
