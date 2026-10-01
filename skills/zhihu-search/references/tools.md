# Tool reference

Per-tool parameters, limits, paging, and identity rules. CLI commands use hyphens; MCP tools
use the same name with underscores (`question-answers` → `question_answers`). Every business
command accepts `--format markdown|json`. `uvx zhihu-search <command> --help` prints the
installed version's exact arguments.

## Search, Zhida, hot list

```bash
uvx zhihu-search search "RAG 评测 方法" --scope zhihu --count 10
uvx zhihu-search search "RAG evaluation benchmark" --scope web --count 20 --search-db realtime
uvx zhihu-search search "向量数据库 选型" --scope web --count 10 --filter "host != example.com"
uvx zhihu-search ask "如何评估 RAG 系统的召回质量？" --model thinking
uvx zhihu-search trending --limit 30
```

- `search`: query 2–100 characters. `--scope zhihu` (default) searches Zhihu, `--count` ≤10;
  `--scope web` searches the web, `--count` ≤20. No pagination.
- `--filter` and `--search-db all|realtime|static` apply to web scope only. Filter syntax:
  `host == x` / `host != x`, `publish_time` comparisons in Unix seconds, uppercase `AND` /
  `OR`. A filter cannot target `zhihu.com`.
- `ask`: Zhihu Zhida answer. `--model fast|thinking|agent`. Output is AI-generated.
- `trending`: Zhihu hot list, `--limit` ≤30.

## Official quota

```bash
uvx zhihu-search quota
uvx zhihu-search quota --api-id question_answers --api-id creator
```

Returns `TotalQuota`, `TotalUsed`, `RemainingQuota` per API group. `--api-id` is repeatable;
values: `global_search`, `zhihu_search`, `hot_list`, `question_answers`, `zhida_openai`,
`tools`, `knowledge`, `user_data`, `creator`. Querying quota is free. All Access Secrets of
one account share the same quota; failed requests are not charged. `--quota` is the global
flag equivalent.

## User data

```bash
uvx zhihu-search user-contents --content-type answer --limit 50 --sort-field like_count --sort-order desc
uvx zhihu-search user-followees --offset 0 --limit 50
uvx zhihu-search user-collections --limit 20
uvx zhihu-search user-favlists --limit 20
uvx zhihu-search favlist-contents --url-token 123456789 --offset 0 --limit 20
```

- `user-contents`: `--content-type all|answer|article|zvideo|pin|question`, `--offset`,
  `--limit` ≤50, `--sort-field like_count|ts`, `--sort-order asc|desc`. Offset-paged.
- `user-followees`: `--offset`, `--limit` ≤50. Offset-paged.
- `user-collections`, `user-favlists`: `--limit` only, no pagination.
- `favlist-contents`: `--url-token` (or legacy `--id`), `--offset`, `--limit`. Offset-paged.
- Identity: with `ZHIHU_OAUTH_TOKEN` configured the CLI acts as the OAuth-authorized user;
  otherwise as the developer account owning the Access Secret. In MCP, the
  `use_configured_oauth_user` argument selects the identity.
- Quota group: `user_data`.

## Questions

```bash
uvx zhihu-search question-recommendations --count 10
uvx zhihu-search question-recommendations --query "大模型 应用落地" --count 5
uvx zhihu-search question-answers "https://www.zhihu.com/question/123456789" --offset 0 --limit 50
```

- `question-recommendations`: `--count` 1–20 (default 5). Without `--query`, results follow
  the account profile; a whitespace-only query is invalid. No paging; may return fewer than
  `--count`. Uses the Access Secret; OAuth is not accepted. Quota group: `creator`.
- `question-answers`: answers under a question URL. `--offset`, `--limit` 1–50. Returns
  upstream `Summary` excerpts, not full text. Uses the Access Secret; OAuth is not accepted.
  Quota group: `question_answers`.

## Own content and creator statistics

```bash
uvx zhihu-search user-content-detail "https://www.zhihu.com/answer/123456789"
uvx zhihu-search user-content-comments "https://zhuanlan.zhihu.com/p/123456789" --limit 50 --order score
uvx zhihu-search creator-account-stats --content-type all --start-date 2026-09-01 --end-date 2026-09-30
uvx zhihu-search creator-content-stats "https://www.zhihu.com/pin/123456789"
```

- Owner-only: these work only on content published by the account itself. Content that
  cannot be confirmed as owned returns `10001`.
- Accepted URLs: `/answer/{id}`, `/question/{id}/answer/{id}`, `zhuanlan.zhihu.com/p/{id}`,
  `/pin/{id}`, `/zvideo/{id}` (video returns associated text only).
- `user-content-comments`: `--offset`, `--limit` 1–50 root comments,
  `--order score|reverse|ascending`. Offset-paged. Child comments may be partial; the total
  count may differ from the number of reachable comments.
- `creator-account-stats`: `--content-type all|answer|article|pin|zvideo`.
  `creator-content-stats`: one own content URL. Both take optional `--start-date` and
  `--end-date` (`YYYY-MM-DD`), given together or omitted together.
- Statistics may lag. Empty `Items` does not mean zero metrics. Rates are returned as given.
- Quota group: `creator` (shared by detail, comments, and stats).

## Knowledge bases

```bash
uvx zhihu-search knowledge-bases --scope all
uvx zhihu-search knowledge-items kb_123456 --limit 20
uvx zhihu-search knowledge-search "RAG 召回评估" --knowledge-base-id kb_123456 --limit 10
uvx zhihu-search knowledge-search "RAG 召回评估" --recall-scope personal --recall-scope public
uvx zhihu-search knowledge-upload ./notes.pdf --knowledge-base-id kb_123456
```

- `knowledge-bases`: `--scope all|created|subscribed`.
- `knowledge-items`: `--cursor`, `--limit` ≤20. Cursor-paged via `HasMore` / `NextCursor`.
- `knowledge-search`: `--knowledge-base-id` (repeatable) and/or
  `--recall-scope personal|subscription|public` (repeatable). At least one is required; both
  together are a union. `--limit` ≤10 documents.
- `knowledge-upload` (CLI only): synchronous upload and parse. Without
  `--knowledge-base-id` the file goes to the default knowledge base. File ≤100 MB, file name
  ≤255 UTF-8 bytes. Extensions: pdf, md, txt, ppt, pptx, xls, xlsx, csv, doc, docx, webp, png,
  jpg, mobi, epub, azw3. First use requires initializing the knowledge base at
  <https://zhida.zhihu.com/repositories/square>. If the upload times out, its outcome is
  unknown.
- Quota group: `knowledge`.

## PDF parsing and PPT generation

```bash
uvx zhihu-search pdf-upload ./paper.pdf
uvx zhihu-search pdf-create 64f0c0ffee0000000000abcd --idempotency-key paper-v1
uvx zhihu-search pdf-status task_123456
uvx zhihu-search ppt-create "https://www.zhihu.com/answer/123456789" --pages 12 --idempotency-key deck-v1
uvx zhihu-search ppt-status task_654321
```

- `pdf-upload` (CLI only): local PDF ≤100 MB, separate daily limit. Returns a `file_id`
  valid for 24 hours.
- `pdf-create`: creates a parse task from a `file_id`; `pdf-status` returns task state and
  result URLs. Result URLs are short-lived; a new `pdf-status` call returns fresh ones.
- `ppt-create`: Zhihu answer or column-article URL, `--pages` 6–21 (default 12);
  `ppt-status` returns task state and the result.
- `--idempotency-key`: optional; reusing a key with different input returns `40001`.
- Quota group: `tools` (PDF and PPT shared). Charged only when a task succeeds; status
  queries are free.

## OAuth (CLI only)

```bash
uvx zhihu-search oauth-url my_app_id "https://example.com/callback"
uvx zhihu-search oauth-token my_app_id "https://example.com/callback" auth_code_value
```

- `oauth-url`: builds the authorization URL for an app id and registered redirect URI.
- `oauth-token`: exchanges the callback `code` for an access token. Reads the app key from
  `ZHIHU_OAUTH_APP_KEY`. The output is a credential; store it as `ZHIHU_OAUTH_TOKEN` for the
  user-data tools.

## Other commands

- `serve --tools <profile|tool,…>`: starts the stdio MCP server with the given profile or
  tool names (see the profile table in SKILL.md).
- `install-skill [--agent <name>] [--project] [--copy]`: installs this Skill via
  `npx skills`; see [setup](setup.md).
