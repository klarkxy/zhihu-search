# DeepSeek Harness

`dsh-plugin-zhihu-search` is a declarative DSH bundle. It inserts DSH's
built-in `@deepseek-ai/dsh-mcp-client`, which starts the pinned Python MCP
server over stdio and publishes server-qualified native tools.

## Prerequisites

Install [uv](https://docs.astral.sh/uv/) and make sure `uvx` is available to
the same OS user that starts DSH:

```powershell
uvx --version
uvx zhihu-search --version
```

Save and verify the Access Secret locally before starting the profile:

```powershell
uvx zhihu-search --save-token "<Access Secret>"
uvx zhihu-search --probe
```

Never put the Access Secret in `cordis.patch.yml`, DSH profile metadata,
chat, screenshots, or logs. The bundle uses the existing per-user Python
credential file and contains no secret-bearing configuration.

## Install the bundle

Install the repository directly from GitHub into the profile that should
expose Zhihu:

```powershell
dsh plugin --profile web add "github:klarkxy/zhihu-search"
```

No npm publication or install-time build permission is required: this bundle
contains only a manifest and a declarative patch, with no `prepare` or other
package scripts. For a local checkout:

```powershell
dsh plugin --profile web add .
```

For production or reproducible setups, replace `<commit>` with a reviewed Git
commit SHA:

```powershell
dsh plugin --profile web add "github:klarkxy/zhihu-search#<commit>"
```

Inspect the composed profile before starting it:

```powershell
dsh --profile web --dump-config
```

The dump must contain one `zhihu-search-mcp` row using
`@deepseek-ai/dsh-mcp-client`, `command: uvx`, the pinned
`zhihu-search==<version>` package, and `serve --tools compact`. A persistent
installation requires stopping and restarting the target DSH profile.

## Verify the live capability

Wait for these four initial tools to appear exactly once:

- `mcp__zhihu__search`
- `mcp__zhihu__ask`
- `mcp__zhihu__trending`
- `mcp__zhihu__other`

Use a request that expects inspectable sources, for example:

> 帮我查一下最近主流的 RAG 评测方法，返回两条并附来源链接。

Completion requires a real DSH tool call, a successful matching tool result,
and a non-empty task answer containing useful links. A successful package
install or config dump alone is not end-to-end proof.

In compact mode, `other(action="enable")` should reveal nine additional
low-frequency tools. DSH's MCP client owns subprocess shutdown and bounded
reconnection; recovered tools must not be duplicated.

## Update and remove

```powershell
dsh plugin --profile web update dsh-plugin-zhihu-search
dsh plugin --profile web remove dsh-plugin-zhihu-search
```

`update` follows the GitHub specification already recorded in the profile. A
commit-pinned installation moves only when it is re-added with a different
reviewed SHA.

Removal must eliminate the bundle layer and its MCP subprocess after the
profile restarts. It intentionally preserves the independent Python
credential file. Remove that only on explicit user request:

```powershell
uvx zhihu-search --clear-token
```
