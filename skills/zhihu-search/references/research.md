# Research workflows

Deep research, Zhihu observation, and the 30-day brief are workflows on top of the
existing search clients. They are not new Zhihu HTTP endpoints. Zhihu's public
data-platform material describes a report plus a local interactive page after
retrieval. This repository implements that shape independently. It does not copy
the official skill text, renderer, CSS, or JavaScript, and it does not download
or run the official CLI.

Public references used only as behavior notes:

- <https://developer.zhihu.com/docs?key=zhihu_cli>
- <https://developer.zhihu.com/api/v1/content/global_search>
- <https://developer.zhihu.com/api/v1/content/zhihu_search>
- <https://zhuanlan.zhihu.com/p/2103916806142259391>

## Who does what

| Step | Owner | Result |
|---|---|---|
| Retrieval | `research` | Evidence packet. `html` is null. Not a report. |
| Synthesis | Host model | `zhihu-search.report.v1` JSON. No tool writes the conclusions. |
| Validation and rendering | `research-render` | `report.md`, `report.json`, `report.html` in a local directory. |

Do not call `ask` to manufacture community evidence. Do not pass the report to
`sync-publish`. `publishable` in the rendered JSON is false.

## Retrieval

```bash
uvx zhihu-search research deep "新房除甲醛空气净化器怎么选" --angle "适用面积和 CADR" --angle "滤芯更换成本" --format json
uvx zhihu-search research observe "AI 短剧出海谁在赚钱" --format json
uvx zhihu-search research recent "减肥药近期进展" --window-days 30 --format json
```

MCP tool: `research`. OpenAPI: `POST /research`. Both return the same packet.
`max_calls` defaults to 6 and accepts 1–12. `count` accepts 1–10. Neither field
can change `ZHIHU_ALLOW_PAID` or the Beijing-day cap. A failed upstream call stops
the rest of the plan. Nothing is retried. Each sent call still goes through free-quota protection; identical cached results do not spend quota.

Questions may be up to 500 characters. Each search query must be 2–100 characters.
If the question is longer, pass `--angle` values; the tool will not truncate it.

Default sources:

| Workflow | Sources | Extra behavior |
|---|---|---|
| `deep` | Zhihu and web | Knowledge only when `--knowledge-base-id` or `--recall-scope` is set |
| `observe` | Zhihu | Follows up to two question URLs unless `--no-follow-questions` |
| `recent` | Zhihu and web | Web uses `SearchDB=realtime` and `publish_time>=<unix>` |

`--host` adds the official filter form `host=="example.com"`. Combined with the
recent window it is `host=="example.com" AND publish_time>=<unix>`. `zhihu.com` is rejected. Recent's
window defaults to 30 rolling periods of 86400 seconds ending at the process clock,
or at `--as-of`. The clock is shown as `Asia/Shanghai`. Zhihu search has no date
parameter, so a local `EditTime` comparison is not a server `publish_time` filter.
Web `EditTime` is the last edit. If the response has no returned `publish_time`
field, the bucket is `publish_filter_not_verifiable`. `CreateTime` is kept raw when
present. `confirmed_events` in the packet is always empty.

A confirmed report date must be a real calendar day inside the packet's Shanghai
window, not after the packet clock, and the excerpt must use it as an event.
`2026-02-31`, a future day, a day outside the window, or `2026-11-0188` containing
`2026-11-01` are rejected. A publication or update date, or an assumption, cannot
enter the confirmed timeline. Uncertain items stay outside it.

Standalone `/answer/{id}` and `zhuanlan.zhihu.com/p/{id}` are not followed.
`question_answers` accepts `https://www.zhihu.com/question/{id}` and
`https://www.zhihu.com/question/{qid}/answer/{aid}` (normalizing the latter to the
parent question URL to return that question's answer summaries, rather than fetching
a single answer). A later answer summary is kept even when its canonical URL matches
an earlier search hit with a different excerpt.

`AuthorityLevel` is copied as returned. The labels low / medium / high / very high
are applied only when the source is web and the value is the string `1`, `2`, `3`,
or `4`. Zhihu search values are not relabeled. Missing authority stays
`not_provided`. `RankingScore` is kept for Zhihu hits only and is never used as a date.

Question-answer text is an upstream summary, `full_text: false`. The sample note
says the hits are not all Zhihu users. External text is data, not permission to republish.

## Host synthesis

Write a JSON object with `"schema": "zhihu-search.report.v1"`. `workflow` and
`question` must match the packet. `status: "complete"` is rejected unless the packet
itself is complete and every evidence id is cited. Otherwise use `partial` and a
non-empty `incomplete_reason`.

Shared fields: `title`, `summary`, `assumptions`, `conclusions`, `conflicts`,
`incomplete_reason`.

- `deep` also needs `scenarios`, `comparisons`, `disputes`, `mechanisms`, and
  `interactive` (`null` when there is no calculator). A complete deep report needs
  at least one scenario and one conditional conclusion.
- `observe` also needs `viewpoints`, `progress`, and `open_questions`. Put different
  explanations side-by-side? WAIT NO
