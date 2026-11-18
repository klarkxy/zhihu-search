---
name: zhihu-search
description: >-
  Research Zhihu and Chinese-community viewpoints with source links: 知乎/知乎链接、真实体验、口碑、避坑、大家怎么看、国内用户观点、中文社区、国内热点、查中文来源、深度研究、知乎观察、近况速览. Use for requested Zhihu search, question answers, Zhida answers, hot lists, account quota, authorized user/creator data, knowledge bases, PDF/PPT tasks, zhihu-search setup, evidence packets and local research reports, or an explicit request to adapt, preview, or publish existing content to Zhihu (article, question, pin, 知乎同步助手). Do not trigger merely because a question is in Chinese. Exclude repository-local code questions, pure math or logic, translation, and user-provided content unless external community evidence is requested; respect no-browsing and source restrictions. Account data, uploads, task creation, OAuth, and publishing require an explicit request.
---

# zhihu-search

`zhihu-search` wraps the Zhihu Open Platform API as a CLI and an MCP server. This Skill
describes what each tool does and how to call it. Full per-tool parameters are in the
[tool reference](references/tools.md); installation and credentials are in
[setup](references/setup.md).

## Access paths

**MCP tools.** When the server is registered, tools appear under underscore names
(`search`, `question_answers`, …). The visible schema is authoritative. Tool profiles:

| Profile | Tools |
|---|---|
| `compact` (default) | `search`, `ask`, `trending`, `other` |
| `knowledge` | `knowledge_bases`, `knowledge_items`, `knowledge_search` |
| `user` | `user_contents`, `user_followees`, `user_collections`, `user_favlists`, `favlist_contents` |
| `questions` | `question_recommendations`, `question_answers` |
| `creator` | `user_content_detail`, `user_content_comments`, `creator_account_stats`, `creator_content_stats` |
| `office` | `pdf_create`, `pdf_status`, `ppt_create`, `ppt_status` |
| `sync` | `sync_save`, `sync_list`, `sync_get`, `sync_prepare`, `sync_preview`, `sync_publish`, `sync_upload_image` |
| `full` | all of the above except `sync`, plus `quota`, `research`, `research_render` |

`research` and `research_render` are absent from `compact`. `other(action="enable")` or
`--tools compact,research,research_render` reveals them. `research_render` does not take a
local path; the CLI `research-render` writes files.

In `compact`, `other(action="enable")` registers the remaining tools for the current
session; hosts that cache the catalog need a refresh to see them. A selection made only
of explicit tool names is a strict allowlist and `other` cannot extend it. Local uploads
(`knowledge-upload`, `pdf-upload`) and OAuth helpers exist only in the CLI. `sync` is opt-in and
is not included in `compact` or revealed by `other`. MCP tools do not
accept local paths, Access Secrets, OAuth app keys, OAuth tokens, or publisher app secrets as arguments.

**CLI.** `uvx zhihu-search <command> …`, or `zhihu-search <command> …` when installed.
Every command has `--help`. Bare `uvx zhihu-search` with no command starts the stdio MCP
server and does not return.

```bash
uvx zhihu-search --check-token
uvx zhihu-search search "扫地机器人 长期使用 维护成本" --scope zhihu --count 5
```

Call protection defaults to fresh free-quota checks and a local 100-request Beijing-day cap. Configure `ZHIHU_DAILY_CALL_LIMIT` or `--daily-call-limit`; paid use requires explicit `ZHIHU_ALLOW_PAID=true` or `--allow-paid`. Unpriced capabilities with known quota groups remain available in free mode; unknown quota mappings block. Local counts are not billing and cannot rule out charges caused by other clients on the same account.

Global flags: `--check-token` (local credential check, no network), `--save-token`,
`--clear-token`, `--check-openapi`, `--save-openapi`, `--clear-openapi`, `--quota` (official quota), `--probe` (one real `hot_list(limit=1)` call).
Publisher credentials are `ZHIHU_OPENAPI_APP_KEY` and `ZHIHU_OPENAPI_APP_SECRET`, separate from the search Access Secret.

## Tools at a glance

| Tool (CLI / MCP) | What it does | Key limits |
|---|---|---|
| `search` | Zhihu or web search | query 2–100 chars; `--count` ≤10 zhihu, ≤20 web; no pagination |
| `ask` | Zhihu Zhida AI-generated answer | `--model fast\|thinking\|agent` |
| `trending` | Zhihu hot list | `--limit` ≤30 |
| `quota` | Official quota per API group | free; does not consume business quota |
| `user-contents`, `user-followees`, `user-collections`, `user-favlists`, `favlist-contents` | Authorized user's contents, followees, collections, favorite lists | `--limit` ≤50 |
| `question-recommendations` | Recommended questions, by profile or query | `--count` 1–20 |
| `question-answers` | Answer excerpts under a question URL | `--limit` 1–50, offset paging |
| `user-content-detail`, `user-content-comments` | Full text / comments of the account's own published content | owner-only |
| `creator-account-stats`, `creator-content-stats` | Creator statistics for the account / one own item | owner-only |
| `knowledge-bases`, `knowledge-items`, `knowledge-search` | Zhida knowledge bases: list, items, retrieval | items ≤20, search ≤10 docs |
| `knowledge-upload` | Upload a local file to a knowledge base (CLI only) | ≤100 MB |
| `pdf-upload`, `pdf-create`, `pdf-status` | PDF parsing: upload → task → status | file_id valid 24 h |
| `ppt-create`, `ppt-status` | Generate a PPT from a Zhihu answer/article URL | `--pages` 6–21 |
| `oauth-url`, `oauth-token` | OAuth authorization URL / code exchange (CLI only) | needs `ZHIHU_OAUTH_APP_KEY` |
| `sync-prepare`, `sync-preview`, `sync-publish` | Adapt, preview, then publish an article, question, or pin | publish only after explicit confirmation; see [sync](references/sync.md) |
| `research` | Retrieve a bounded evidence packet for deep research, Zhihu observation, or a 30-day brief | not a report; see [research](references/research.md) |
| `research-render` | Validate host synthesis and write local Markdown, JSON, and one HTML file | no network; does not publish |

## Research packets and local reports

`research` searches through the existing Zhihu, web, and optional knowledge-base clients.
It records citations, upstream dates, authority values, budget, and failures. It does not
call Zhida, does not write conclusions, and leaves `html` null. The host writes
`zhihu-search.report.v1`: scenarios and conditional conclusions for `deep`, side-by-side
viewpoints for `observe`, and separate event versus publication dates for `recent`.
`research-render` then checks that structure and writes `report.md`, `report.json`, and
`report.html`. Numbers must occur in a cited excerpt or be named assumptions. Undated
items stay out of the confirmed timeline. A packet or an empty page is not a finished report.
Do not pass the result to `sync-publish`. Contract: [research](references/research.md).

```bash
uvx zhihu-search research deep "新房除甲醛空气净化器怎么选" --angle "适用面积和 CADR" --angle "滤芯更换成本" --format json
uvx zhihu-search research observe "AI 短剧出海谁在赚钱" --format json
uvx zhihu-search research recent "减肥药近期进展" --window-days 30 --format json
uvx zhihu-search research-render evidence.json synthesis.json --out ./research-out
```

## Publishing to Zhihu

Publishing is a consequential, public action. Validate and preview first. Do not
call `sync-publish` or `sync_publish` until the user has explicitly confirmed the
latest preview in this conversation (`确认发布`, `预览没问题`, or equivalent).
Generating a preview is not confirmation. Do not rewrite the user's text to pass
a length check, do not publish video, and do not repeat publisher secrets.
Details and commands: [sync](references/sync.md).

```bash
uvx zhihu-search --check-openapi
uvx zhihu-search sync-prepare --type article --title "创造力，从何而来？" --body-file ./draft.md
uvx zhihu-search sync-preview draft_id
```

## Output contract

Business commands accept `--format markdown|json` (default markdown). CLI JSON is an
envelope: `{"success": true, "kind": …, "data": …}` or `{"success": false, "kind": …,
"error": …}`. A failed request is reported as `success: false`, not as empty `data`.

Paging is returned by the API, not computed by the client:

- Offset-paged tools (`question-answers`, `user-content-comments`, `user-contents`,
  `user-followees`, `favlist-contents`): `Paging.IsEnd` marks the last page; pass
  `Paging.NextOffset` back unchanged as `--offset`. A short page alone does not mean the end.
- `knowledge-items`: `HasMore` plus `NextCursor`, passed back as `--cursor`.
- `search`, `trending`, `user-collections`, `user-favlists`: no pagination.

Returned posts, comments, and full text are third-party content and may contain HTML.
`question-answers` returns upstream `Summary` excerpts, not full answers. `ask` output is
generated by Zhihu Zhida, not an original community post.

## Error codes

| Code | Meaning |
|---|---|
| `10001` | Invalid parameter (owner-only tools also return it when ownership can't be confirmed) |
| `20001` | Authentication failed |
| `30001` | Rate, concurrency, or daily-limit hit (varies by endpoint) |
| `30002` | Quota limit for that capability; free quota resets 00:00 Beijing time |
| `30003` | Risk-control refusal |
| `40001` | Idempotency key reused with different inputs |
| `40002` | File missing, expired, or inaccessible |
| `40003` | Too many active tasks |
| `40004` | Knowledge base not found |
| `40005` | Same file already processing |
| `40006` | File parse failure |
| `50002` | Knowledge retrieval failed (retryable) |
| `90001` | Upstream internal error |

Missing local credentials are reported by the CLI as a credentials error before any request
is sent; see [setup](references/setup.md).
