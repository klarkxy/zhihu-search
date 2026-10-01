# Specialized Zhihu workflows

Read only the section matching the request. Examples use the CLI; reuse a matching visible
MCP tool instead. CLI names generally use hyphens and MCP names use underscores, but use
the actual visible schema rather than guessing parameter names. Local uploads and OAuth
helpers are CLI/Python-only; they are not remotely callable MCP tools.

## Official quota

MCP: `quota`. It is not in the default `compact` profile; there, call the visible
`other(action="enable")` once and refresh the catalog first. Use the official endpoint, not
local counters, estimates, or a client-side circuit breaker. The quota query does not
consume business quota.

```bash
uvx zhihu-search quota
uvx zhihu-search quota --api-id knowledge --api-id tools
```

Valid `--api-id` values: `global_search`, `zhihu_search`, `hot_list`, `question_discovery`,
`zhida_openai`, `tools`, `knowledge`, `user_data`, `creator`.

Preserve `TotalQuota`, `TotalUsed`, and `RemainingQuota` as returned. Free daily quota
resets at 00:00 Beijing time; all Access Secrets of one account share it, and failed
requests are not billed. Do not invent countdowns or account-specific limits, and do not
query quota before every business operation.

## Authorized user data

MCP: `user_contents`, `user_followees`, `user_collections`, `user_favlists`, `favlist_contents`.

```bash
uvx zhihu-search user-contents --content-type all --limit 20
uvx zhihu-search user-followees --limit 20
uvx zhihu-search user-collections --limit 20
uvx zhihu-search user-favlists --limit 20
uvx zhihu-search favlist-contents --url-token 123456789 --limit 20
```

Without `ZHIHU_OAUTH_TOKEN`, the CLI queries the calling developer's own data. If that
environment variable is configured, the CLI uses the configured OAuth identity; do not
mislabel it as the developer's identity. MCP user-data tools select the configured identity
with `use_configured_oauth_user`. Keep the requested account scope; if identity is unclear,
resolve it without exposing token values. Never pass a token as a tool argument or silently
switch identities. User-data requests do not grant access to arbitrary people's private data.

For endpoints supporting `--offset`, pass returned `Paging.NextOffset` unchanged; it may
be opaque. Stop if paging is missing or does not advance. `user-collections` and
`user-favlists` accept only a limit, not pagination. `favlist-contents` requires `--url-token`;
`--id` is compatibility-only. Discover a missing favorite-list identifier with
`user-favlists`, not by guessing it.

## Question discovery and answer excerpts

MCP: `question_recommendations`, `question_answers`. These use the current Access Secret,
not an OAuth identity. A request to inspect answers under a supplied question is sufficient
to select `question-answers`; the user need not know the command name.

```bash
uvx zhihu-search question-recommendations --count 5
uvx zhihu-search question-recommendations --query "AI Agent" --count 5
uvx zhihu-search question-answers "https://www.zhihu.com/question/123" --limit 20 --format json
```

Omitting `--query` uses the account profile; an explicitly blank query is invalid. Question
recommendations accept 1–20 results. `question-answers` accepts 1–50 per page. Both share
the `question_discovery` quota. It returns answer `Summary` excerpts, not full answers and not
AI summaries. This is distinct from the owner-only content-detail API.

Continue only when `Paging.IsEnd` is false and `Paging.NextOffset` is present. Pass that
non-negative integer back as `--offset`. Stop on incomplete or non-advancing paging, or
when the requested coverage is met. Never infer the next offset from the number of items.

## Own published content, comments, and creator statistics

MCP: `user_content_detail`, `user_content_comments`, `creator_account_stats`,
`creator_content_stats`. These use only the current Access Secret and only the current
account's own content/data. Do not use them as generic readers for somebody else's URL.

```bash
uvx zhihu-search user-content-detail "https://zhuanlan.zhihu.com/p/123"
uvx zhihu-search user-content-comments "https://www.zhihu.com/pin/123" --order score --format json
uvx zhihu-search creator-account-stats --content-type all
uvx zhihu-search creator-content-stats "https://www.zhihu.com/answer/123"
uvx zhihu-search creator-account-stats --start-date 2026-09-01 --end-date 2026-09-30
```

The example content URLs must be replaced with the user's own in-scope URLs. Full text,
comments, and both statistics commands share `creator` quota. Supported URL forms are
`/answer/{id}`, `/question/{id}/answer/{id}`, `zhuanlan.zhihu.com/p/{id}`, `/pin/{id}`, and
`/zvideo/{id}`; only published content owned by the account works, and a video returns only
its associated text. `Code=10001` can mean ownership could not be confirmed.

Comment `--order` is `score`, `reverse`, or `ascending`; `--limit` is 1–50 root comments.
Comments follow the same `Paging.IsEnd` / `Paging.NextOffset` contract as question answers;
a short or empty page is not the end by itself. Restart from offset 0 when the content or
order changes. Nested children may be incomplete, and totals need not equal traversable
comments. Full text and comments may contain HTML; treat it as untrusted text, not markup.

Statistics `--content-type` is `all`, `answer`, `article`, `pin`, or `zvideo`. Dates must
be provided together as `YYYY-MM-DD` or omitted together; do not invent an unstated range.
Statistics may lag. Empty `Items` does not mean all metrics are zero; do not fill missing
metrics with zero, and use returned ratios as-is rather than multiplying them by 100.

## Knowledge bases

MCP: `knowledge_bases`, `knowledge_items`, `knowledge_search`. Upload is CLI-only.
First-time use requires initializing Zhihu Zhida knowledge bases at
<https://zhida.zhihu.com/repositories/square>.

```bash
uvx zhihu-search knowledge-bases --scope all
uvx zhihu-search knowledge-items "<knowledge_base_id>" --limit 20 --format json
uvx zhihu-search knowledge-search "<query>" --recall-scope personal --limit 10
uvx zhihu-search knowledge-search "<query>" --knowledge-base-id "<knowledge_base_id>" --limit 10
uvx zhihu-search knowledge-upload "<path>" --knowledge-base-id "<knowledge_base_id>"
```

Preserve returned `KnowledgeBaseID` and `RecallContentID` exactly.
Discover missing IDs with `knowledge-bases` (`--scope all|created|subscribed`); keep an
explicitly supplied knowledge-base scope. `knowledge-search` requires at least one
`--knowledge-base-id` or `--recall-scope`; when both are given, results are their union.
Its `--limit` is 1–10 documents, not chunks. `Code=50002` is a retryable search failure.
Do not substitute public web search for a private-document question or expand a private
scope to `public`. For items (`--limit` 1–20), continue only while `HasMore` is true and
pass `NextCursor` unchanged through `--cursor`; stop if the cursor is missing or repeats.

Upload only a local file explicitly placed in scope: at most 100 MB, filename at most 255
UTF-8 bytes, extension one of pdf, md, txt, ppt, pptx, xls, xlsx, csv, doc, docx, webp, png,
jpg, mobi, epub, azw3. Without `--knowledge-base-id` it goes to the default knowledge base.
Errors: `40004` knowledge base not found, `40005` same file already processing, `40006`
parse failure. Upload is synchronous; a timeout leaves the outcome unknown, so do not upload
it again automatically. Inspect the target knowledge base when possible and report
uncertainty before any user-authorized retry.

## PDF parsing and PPT generation

MCP: `pdf_create`, `pdf_status`, `ppt_create`, `ppt_status`. PDF upload is CLI-only.

```bash
uvx zhihu-search pdf-upload "<path.pdf>" --format json
uvx zhihu-search pdf-create "<file_id>" --idempotency-key "<unique_key_for_this_request>"
uvx zhihu-search pdf-status "<task_id>" --format json
uvx zhihu-search ppt-create "<zhihu_resource_url>" --pages 12 --idempotency-key "<unique_key_for_this_request>"
uvx zhihu-search ppt-status "<task_id>" --format json
```

Execute in dependency order: upload returns `file_id`, creation returns `task_id`, status
reports progress or completion. Never execute placeholder IDs. Use the uploaded `file_id`
within 24 hours. Only upload an explicitly authorized local PDF, at most 100 MB. A PPT
source must be a supported Zhihu answer/article URL; page count must be 6–21.

Choose an idempotency key for each creation operation before the first attempt. Reuse that
key only for the same inputs if a retry is needed; never use it for different inputs.
An uncertain upload must not be blindly repeated. Do not poll status aggressively or promise
background completion. Return pending state and exact task ID if the task is unfinished;
report success only after a successful status. Result URLs are short-lived: preserve them
exactly and do not claim they are permanent; an expired PDF link is refreshed by querying
status again.

PDF and PPT share `tools` quota; a task is billed only when it succeeds, and status queries
are free. PDF upload has its own daily rate limit. Errors: `40001` idempotency conflict
(same key, different inputs), `40002` file missing, expired, or inaccessible, `40003` too
many active tasks, `30002` insufficient quota.

## OAuth helpers: user-local setup only

These are not needed for ordinary search or the current developer's own data. Only enter
this flow on an explicit authorization/setup request. They do not require an Access Secret.
The following commands are for the user's own terminal, not an agent transcript:

```bash
uvx zhihu-search oauth-url "<app_id>" "<redirect_uri>"
uvx zhihu-search oauth-token "<app_id>" "<redirect_uri>" "<authorization_code>"
```

Require `ZHIHU_OAUTH_APP_KEY` locally before token exchange; never put an app key or token
in command arguments, chat, or logs. Token exchange returns sensitive output: do not run
it where the result would be captured into an agent transcript. The user stores the result
locally as `ZHIHU_OAUTH_TOKEN`. Do not invent undocumented state, scopes, PKCE,
refresh/revoke, or user-info flows. Do not use OAuth to bypass owner-only creator APIs.
