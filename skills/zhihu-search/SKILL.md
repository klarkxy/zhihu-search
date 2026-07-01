---
name: zhihu-search
description: Use the zhihu-search CLI directly for live Zhihu search, Zhihu Zhida answers, and trending topics. Trigger when the user asks to search Zhihu, query Zhihu content, ask Zhihu Zhida, inspect Zhihu trending/hot list, compare Zhihu results, or fetch current information from developer.zhihu.com-backed Zhihu APIs.
---

# zhihu-search

Use `zhihu-search` as a live CLI tool first. This skill is not an installation wizard or MCP setup guide.

## Core Rule

When a user asks for Zhihu search, Zhihu Zhida, or Zhihu trending information:

1. Check the CLI and credential state.
2. Run the appropriate `zhihu-search` CLI command.
3. Summarize the returned results with links and the quota line.
4. Only discuss installation/configuration if the CLI is missing or credentials are unavailable.

Never ask the user to paste an Access Secret into chat.

## Preflight

Run:

```bash
zhihu-search --check-token
```

If the command is missing, use one fallback:

```bash
uvx zhihu-search --check-token
```

If both are missing, explain that the CLI is not available and give the shortest local install command:

```bash
pip install zhihu-search
```

If credentials are missing, tell the user to create an Access Secret at <https://developer.zhihu.com/personal> and save it locally. Do not collect the secret in chat.

```bash
zhihu-search --save-token "<your Access Secret>"
```

## Commands

### Search Zhihu

Use for "搜知乎", "查知乎", "知乎上有没有", "找回答/文章/问题".

```bash
zhihu-search search "<query>" --scope zhihu --count 5
```

Use `--count 10` only when the user wants broader coverage.

### Search Web

Use when the user wants web-wide results through the Zhihu search API.

```bash
zhihu-search search "<query>" --scope web --count 10
```

For domain filtering:

```bash
zhihu-search search "<query>" --scope web --count 10 --filter 'host=="example.com"'
```

### Ask Zhida

Use when the user wants a direct answer from Zhihu Zhida rather than a list of results.

```bash
zhihu-search ask "<question>" --model fast
```

Use `--model thinking` for complex analysis. Use `--model agent` only when the user explicitly wants the slower agent mode.

### Trending

Use when the user asks for Zhihu hot list, trending topics, or "现在知乎在聊什么".

```bash
zhihu-search trending --limit 10
```

## Output Handling

Prefer the default Markdown output for human-facing answers. Use JSON only when you need structured post-processing:

```bash
zhihu-search search "<query>" --scope zhihu --count 5 --format json
```

When answering the user:

- Include the most relevant titles and links.
- Preserve important source attribution from the CLI output.
- Mention the quota/status line if present, especially when quota is low or a circuit breaker is open.
- If results are weak or empty, say so clearly and suggest a narrower query.

## Diagnostics

Use these only when a CLI call fails or the user asks about status:

```bash
zhihu-search --quota
zhihu-search --probe
zhihu-search --reset-quota
zhihu-search --help
```

`--reset-quota` is for local debugging. Do not use it casually.
