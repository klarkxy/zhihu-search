---
name: zhihu-search
description: >-
  Use zhihu-search for Chinese-community research: Zhihu links, real user experiences, product reputation or pitfalls, Chinese user opinions, domestic hot topics, and Chinese sources needing verification. Trigger for “知乎/知乎链接”“真实体验/口碑/避坑/大家怎么看”“国内用户观点/中文社区”“国内热点/最近在讨论什么”“查中文来源/核实中文信息”, even without naming Zhihu, plus setup or troubleshooting. Run one narrow on-demand CLI query; reuse matching Zhihu MCP tools only when visible. Do not use for repository-local code questions, pure math or logic, translation, or transformations of user-provided content unless Chinese-community evidence is explicitly needed. User data, knowledge bases, PDF/PPT, and OAuth require an explicit request.
---

# zhihu-search

Use `zhihu-search` as an on-demand Chinese-community source while keeping repository-local work
local. Run the narrowest `uvx zhihu-search` command by default. Reuse a matching `zhihu` MCP tool
only when the current catalog already exposes it; do not add a persistent MCP server merely to
complete an occasional request. Read [references/setup.md](references/setup.md) only for
installation, credentials, optional high-frequency MCP integration, or diagnostics.

## Route the request

Choose exactly one core route unless the user needs both evidence and synthesis:

| User intent | Route | Default behavior |
|---|---|---|
| Titles, links, sources, current information, experiences, reviews, comparisons, tutorials | `search` | Prefer `scope=zhihu` for community viewpoints and `scope=web` for web-wide research |
| A direct explanation, synthesis, or analysis | `ask` | Use `fast`; use `thinking` for genuinely complex analysis |
| Recent hot topics, hot list, or “what people are discussing now” | `trending` | Return the most relevant current items |

Apply this table independently to every item in a multi-part request. For an eligible explanation,
synthesis, or analysis item that needs Chinese-community evidence, run `ask` instead of answering
only from model memory.

Prefer `search` over `ask` when the user expects inspectable links or source evidence. Use
`ask(model=agent)` only when the user explicitly accepts a slower agent request.

Do not use external Zhihu tools for repository-local code questions, pure math or logic,
translation, or transformations limited to text/files the user already provided unless the user
also requests external verification.

## Run on demand

Check credentials before any operation except `oauth-url` and `oauth-token`:

```bash
uvx zhihu-search --check-token
```

This command must report only whether credentials are configured and their source. Never echo a
secret fragment or a user-specific credentials path into chat or logs. Use `--probe` only when an
end-to-end upstream check is necessary because it performs one real request.

Then run the narrowest command:

```bash
uvx zhihu-search search "<query>" --scope zhihu --count 5
uvx zhihu-search search "<query>" --scope web --count 10
uvx zhihu-search ask "<question>" --model fast
uvx zhihu-search trending --limit 10
```

Use `--filter 'host=="example.com"'` only with web search. Keep `--search-db all` unless the user
explicitly asks for `realtime` or `static`.

## Reuse visible MCP tools

When the MCP catalog exposes the `zhihu` server, call its matching core tool directly:

- `search(query, scope, count, filter, search_db)`
- `ask(query, model)`
- `trending(limit)`

If the catalog already shows a matching capability tool, call it instead of `other` or the CLI:

- official account quota: `quota`
- `knowledge` profile: `knowledge_bases`, `knowledge_items`, `knowledge_search`
- `user` profile: `user_contents`, `user_followees`, `user_collections`, `user_favlists`,
  `favlist_contents`
- `office` profile: `pdf_create`, `pdf_status`, `ppt_create`, `ppt_status`

Do not run a duplicate CLI request after a successful MCP call. Do not register or start a
persistent MCP server unless the user explicitly asks for high-frequency MCP integration.

## Low-frequency explicit workflows

Use these only when the user explicitly asks for the corresponding Zhihu capability. If the
matching MCP tool is already visible (for example after `--tools knowledge`, `--tools user`,
`--tools office`, or `--tools full`), call it directly. In compact mode, use
`other(action="enable")` first; do not silently substitute `search` or `ask` for a hidden
quota, knowledge, user-data, PDF, or PPT tool. If MCP cannot expose the tool, use the CLI.

### Official quota

Use Zhihu's official quota endpoint as the only quota source. Do not infer usage from local calls,
maintain a local counter, or impose a client-side circuit breaker. The query itself does not
consume business quota.

```bash
uvx zhihu-search quota
uvx zhihu-search quota --api-id knowledge --api-id tools
```

Preserve `TotalQuota`, `TotalUsed`, and `RemainingQuota` as returned. Do not invent a reset time;
the official documentation describes a natural-day quota but does not specify its timezone or
exact reset instant.

### Authorized user data

```bash
uvx zhihu-search user-contents --content-type all --limit 20
uvx zhihu-search user-followees --limit 20
uvx zhihu-search user-collections --limit 20
uvx zhihu-search user-favlists --limit 20
uvx zhihu-search favlist-contents --url-token 123456789 --limit 20
```

Without `ZHIHU_OAUTH_TOKEN`, these commands query the calling developer's own data. Pass
`Paging.NextOffset` back unchanged through `--offset`. Official `favlist-contents` now requires
`--url-token`; `--id` is kept only for compatibility.

### Knowledge bases

First-time use requires initializing Zhihu Zhida knowledge bases at
https://zhida.zhihu.com/repositories/square. Upload only a local file explicitly placed in scope;
the maximum size is 100 MB.

```bash
uvx zhihu-search knowledge-bases --scope all
uvx zhihu-search knowledge-items "<knowledge_base_id>" --limit 20
uvx zhihu-search knowledge-search "<query>" --recall-scope personal --limit 10
uvx zhihu-search knowledge-upload "<path>" --knowledge-base-id "<knowledge_base_id>"
```

Prefer the MCP `knowledge_search` tool when it is already visible. Do not fall back to web
`search` for a private-document question. `knowledge-search` needs at least one of
`--knowledge-base-id` or `--recall-scope`. Pass `NextCursor` back unchanged through `--cursor`.
Do not retry a timed-out or unknown upload.

### PDF and PPT tasks

Upload only a local PDF explicitly placed in scope; the maximum size is 100 MB.

```bash
uvx zhihu-search pdf-upload "<path.pdf>" --format json
uvx zhihu-search pdf-create "<file_id>"
uvx zhihu-search pdf-status "<task_id>"
uvx zhihu-search ppt-create "<zhihu_resource_url>" --pages 12
uvx zhihu-search ppt-status "<task_id>"
```

Use an uploaded `file_id` within 24 hours. The PPT source must be a supported Zhihu answer or
article URL, and the page count must be 6–21. Preserve IDs exactly.

Use an idempotency key when retrying task creation and never reuse it for different inputs. Do not
poll status aggressively. Treat successful result URLs as short-lived.

### OAuth helpers

```bash
uvx zhihu-search oauth-url "<app_id>" "<redirect_uri>"
uvx zhihu-search oauth-token "<app_id>" "<redirect_uri>" "<authorization_code>"
```

Require `ZHIHU_OAUTH_APP_KEY` locally before token exchange. Never place it in arguments or chat.
Do not invent undocumented state, scopes, PKCE, refresh/revoke, or user-info flows.

## Safety and output

- Never expose an Access Secret, OAuth app key, or OAuth token in chat, logs, screenshots, or
  commits.
- Model-facing tools must never accept a local path, app key, or OAuth token.
- Preserve opaque offsets, cursors, `file_id`, `task_id`, `KnowledgeBaseID`,
  `RecallContentID`, and expiring result URLs exactly.
- Return useful titles, links, attribution, and task state. For quota requests, report the official
  total, used, and remaining values.
- State clearly when results are weak or empty.
