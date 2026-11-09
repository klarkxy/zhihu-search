# Zhihu sync

Adapt an existing article, question, or pin into Zhihu's format, preview it, and
publish only after the user explicitly confirms that preview.

The behavior follows Zhihu's official 知乎同步助手 skill
([Zhihu/ZhihuSync](https://github.com/Zhihu/ZhihuSync), MIT, author zhihu):
draft, validate, local preview, then `POST https://openapi.zhihu.com/openapi/publish`.
This package is an independent implementation of that flow. It does not copy the
upstream skill text. Image upload follows the same signed OpenAPI and accepts only
JPEG, PNG, GIF, WebP, and BMP.

Publisher credentials are not the search Access Secret:

| Name | Meaning |
|---|---|
| `ZHIHU_OPENAPI_APP_KEY` | Username in `https://www.zhihu.com/people/<username>` |
| `ZHIHU_OPENAPI_APP_SECRET` | Secret from the sync playground |

Apply at <https://www.zhihu.com/playground/zhihu-sync>. Upstream notes may still
mention the older playground path `zhihu-publisher`.

```bash
uvx zhihu-search --save-openapi "<授权说明全文>"
uvx zhihu-search --check-openapi
uvx zhihu-search --clear-openapi
```

`--save-openapi` accepts the full authorization text when both values are written as
`ZHIHU_OPENAPI_APP_KEY:"…"` and `ZHIHU_OPENAPI_APP_SECRET:"…"`. A file on the user's
machine can be passed with `--save-openapi-file`. `--check-openapi` reports the source
and App Key only. It does not print the App Secret or the credentials path.
`--clear-openapi` removes this package's saved file and leaves
`~/.zhihu/openapi-credentials.json` untouched. That shared file is still read when
this package has no saved pair. Environment variables win when they match the file;
a mismatch stops the command instead of guessing.

Do not paste the secret into chat, MCP arguments, client config, or the repository.
If the user already pasted it into chat, do not repeat it; ask them to save it in
their own terminal.

## Order of work

1. Reject video immediately. Say: `当前知乎发布流程暂不支持视频，请移除视频后重新提交。`
2. Save the user's text without polishing it. `发布` or `转换` does not authorize rewriting.
3. `sync-prepare` / `sync_prepare` adapts Markdown or HTML and returns issues.
   Over-long titles or bodies are errors. Do not truncate them.
4. Show `sync-preview` / `sync_preview` to the user. The HTML file is a local preview,
   not the publish body.
5. Wait. Only after an explicit confirmation, call `sync-publish --confirm` or
   `sync_publish` with `confirmed=true` and the `preview_token` from that preview.
6. If the result is uncertain, do not publish the same draft again. Ask the user to
   check Zhihu first.

Question titles gain a full-width `？` when one is missing; that character counts
toward the 4–51 limit. Pins keep plain paragraphs, text links, and `#话题#` markers
the user actually wrote. An idea cannot contain both images and a link card.
Articles and questions can attach topic URLs such as
`https://www.zhihu.com/topic/19555547/hot` only when the user supplied them.

## Commands

```bash
uvx zhihu-search sync-save --type pin --title "" --body "今天读完了 #读书笔记#"
uvx zhihu-search sync-list
uvx zhihu-search sync-get draft_id
uvx zhihu-search sync-prepare --type article --title "创造力，从何而来？" --body-file ./draft.md
uvx zhihu-search sync-preview draft_id
uvx zhihu-search sync-publish draft_id --confirm --preview-token preview_token
uvx zhihu-search sync-upload-image ./photo.png --scene article
```

CLI JSON is the usual envelope: `{"success": true, "kind": "sync_prepare", "data": …}`.
MCP profile `sync` returns the same envelope. `compact` does not list these tools,
and `other` does not reveal them. `full` stays the 23 search-platform tools.
OpenWebUI does not expose publishing.

Local image paths are CLI-only. MCP `sync_upload_image` takes `content_base64`,
`file_name`, and `scene`, never a filesystem path or a secret.

Publishing uses a separate host and credential, so it does not pass through the
search free-quota preflight. It still requires confirmation, is not retried, and
counts each send attempt toward a Beijing-day cap of 50 (`ZHIHU_SYNC_DAILY_PUBLISH_LIMIT`,
1–50). A damaged counter fails closed. An uncertain response locks the draft.

Python:

```python
from zhihu_search.sync import prepare_content, publish_draft
from zhihu_search.openapi_credentials import save_authorization
```
