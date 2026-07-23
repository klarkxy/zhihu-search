---
name: zhihu-search
description: Use uvx to run zhihu-search for live Zhihu search, Zhida answers, trending topics, authorized user data, PDF parsing, PPT generation, and OAuth helper flows.
---

# zhihu-search

This Skill is the preferred entry and uses `uvx zhihu-search` for every operation. Installation
starts in [setup/README.md](../../setup/README.md); agent-led setup and optional high-frequency MCP
configuration belong in [AGENT_SETUP.md](../../AGENT_SETUP.md).

## Core workflow

1. For all operations except `oauth-url` and `oauth-token`, check credentials:

   ```bash
   uvx zhihu-search --check-token
   ```

2. Run the narrowest command that satisfies the request.
3. Return useful titles, links, task state and the quota line.
4. If `uvx` or credentials are unavailable, stop and point to `setup/README.md`.

Never ask the user to paste an Access Secret, OAuth app key or user OAuth token into chat.

## Task routing

### Search, answers and trends

```bash
uvx zhihu-search search "<query>" --scope zhihu --count 5
uvx zhihu-search search "<query>" --scope web --count 10
uvx zhihu-search ask "<question>" --model fast
uvx zhihu-search trending --limit 10
```

Use `--filter 'host=="example.com"'` only for web search. Keep `--search-db all` unless the user
specifically requests `realtime` or `static`. Use `thinking` for complex Zhida analysis and `agent`
only when the user explicitly accepts a slower request.

### User data

```bash
uvx zhihu-search user-contents --content-type all --limit 20
uvx zhihu-search user-followees --limit 20
uvx zhihu-search user-collections --limit 20
uvx zhihu-search user-favlists --limit 20
uvx zhihu-search favlist-contents --url-token 123456789 --limit 20
```

Without `ZHIHU_OAUTH_TOKEN`, these commands query the calling developer's own data. For another
authorized user, configure that token locally without echoing it. Pass `Paging.NextOffset` back
unchanged through `--offset`. `favlist-contents` requires exactly one of `--url-token` or `--id`;
do not invent pagination for collections or favorite-list discovery.

### PDF parsing

Only upload a local PDF that the user explicitly placed in scope. Maximum size is 100 MB.

```bash
uvx zhihu-search pdf-upload "<path.pdf>" --format json
uvx zhihu-search pdf-create "<file_id>"
uvx zhihu-search pdf-status "<task_id>"
```

Use the uploaded `file_id` within 24 hours. Preserve IDs exactly. Status is asynchronous; do not
poll aggressively, and treat successful result URLs as short-lived.

### PPT generation

The source must be a supported Zhihu answer or article URL. Page count must be 6–21.

```bash
uvx zhihu-search ppt-create "<zhihu_resource_url>" --pages 12
uvx zhihu-search ppt-status "<task_id>"
```

Use an idempotency key when retrying task creation, and never reuse it for different inputs.

### OAuth helpers

These commands do not use the developer Access Secret:

```bash
uvx zhihu-search oauth-url "<app_id>" "<redirect_uri>"
uvx zhihu-search oauth-token "<app_id>" "<redirect_uri>" "<authorization_code>"
```

Require `ZHIHU_OAUTH_APP_KEY` locally before token exchange. Never place it in arguments or chat,
and do not invent undocumented state, scopes, PKCE, refresh/revoke or user-info flows.

## Secret and surface safety

- Never expose Access Secret, OAuth app key or OAuth token in chat, logs, screenshots or commits.
- Prefer `ZHIHU_OAUTH_APP_KEY` and `ZHIHU_OAUTH_TOKEN`; do not generate commands containing them.
- Upload only user-scoped local files.
- `pdf-upload`, `oauth-url` and `oauth-token` remain CLI/Python-only.
- Model-facing tools must never accept a local path, app key or OAuth token.
- Preserve opaque offsets, `file_id`, `task_id` and expiring result URLs exactly.

## Output and diagnostics

Use Markdown for people and `--format json` only for structured processing. State when results are
weak or empty; for asynchronous work, report the current state and query again only when useful.

```bash
uvx zhihu-search --quota
uvx zhihu-search --probe
uvx zhihu-search --help
```

`uvx zhihu-search --reset-quota` is for local debugging only; do not use it casually.
