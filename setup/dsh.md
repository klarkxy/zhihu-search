# DeepSeek Harness

`dsh-plugin-zhihu-search` is a declarative DSH bundle. It mounts the
shipped `zhihu-search` Skill into the target profile through DSH's
`@deepseek-ai/dsh-skill-filesystem`. Queries run as on-demand
`uvx zhihu-search` commands. The bundle does not start an MCP server.

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
contains only a manifest, a declarative patch, and the Skill files, with no
`prepare` or other package scripts.

Marketplace and plugin-search tools discover this bundle from the GitHub
topic [`dsh-plugin`](https://github.com/topics/dsh-plugin), not from
`package.json` keywords. Keep that topic on the public repository; `dsh
plugin add` itself does not need it. For a local checkout:

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

The dump must contain one `zhihu-search-skill` row using
`@deepseek-ai/dsh-skill-filesystem`, `providerName: zhihu-search-skill`,
`includeDefaultRoots: false`, and a `bundledSkillDir` that resolves to this
package's `skills` directory. A persistent installation requires stopping
and restarting the target DSH profile.

## Verify the live capability

After restart, the Skill catalog must include `zhihu-search`. Use a request
that expects inspectable sources, for example:

> 帮我查一下最近主流的 RAG 评测方法，返回两条并附来源链接。

Completion requires the agent to load the Skill, run a matching
`uvx zhihu-search` command, and return a non-empty answer with useful
links. A successful package install or config dump alone is not end-to-end
proof.

If credentials are missing, tell the user to open
[知乎开放平台个人中心](https://developer.zhihu.com/personal), save the
Access Secret in their own terminal with `--save-token`, then retry. Never
ask them to paste the Secret into chat.

Do not register a persistent Zhihu MCP server merely because this bundle is
installed. Reuse matching MCP tools only when the current catalog already
exposes them.

If a same-named Skill already exists in the project or user skill roots,
that nearer copy wins over the bundle-shipped Skill.

## Update and remove

```powershell
dsh plugin --profile web update dsh-plugin-zhihu-search
dsh plugin --profile web remove dsh-plugin-zhihu-search
```

`update` follows the GitHub specification already recorded in the profile. A
commit-pinned installation moves only when it is re-added with a different
reviewed SHA.

Removal must eliminate the bundle layer and its Skill provider after the
profile restarts. It intentionally preserves an independently installed
Skill under `~/.agents/skills` and the Python credential file. Remove the
credential only on explicit user request:

```powershell
uvx zhihu-search --clear-token
```
