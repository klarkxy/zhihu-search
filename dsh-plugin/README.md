# dsh-plugin-zhihu-search

DeepSeek Harness bundle for
[`zhihu-search`](https://github.com/klarkxy/zhihu-search). It uses DSH's
built-in MCP client to launch the pinned Python package over stdio; it does
not duplicate the Python business logic or store credentials in DSH config.

## Install

Install [uv](https://docs.astral.sh/uv/) and save the Zhihu Access Secret in
your own terminal first:

```powershell
uvx zhihu-search --save-token "<Access Secret>"
uvx zhihu-search --probe
```

Then install the bundle into the DSH profile you use:

```powershell
dsh plugin --profile web add "github:klarkxy/zhihu-search"
dsh --profile web --dump-config
```

Stop and restart the profile after a persistent install. The initial compact
catalog contains:

- `mcp__zhihu__search`
- `mcp__zhihu__ask`
- `mcp__zhihu__trending`
- `mcp__zhihu__other`

`other(action="enable")` reveals the nine lower-frequency user-data, PDF,
and PPT tools for that MCP session.

For a local checkout smoke test:

```powershell
dsh plugin --profile web add .
```

For a reproducible installation, pin a reviewed commit:

```powershell
dsh plugin --profile web add "github:klarkxy/zhihu-search#<commit>"
```

## Update or remove

```powershell
dsh plugin --profile web update dsh-plugin-zhihu-search
dsh plugin --profile web remove dsh-plugin-zhihu-search
```

Removing the bundle does not remove the independent Python credential file.
Use `uvx zhihu-search --clear-token` only when the user explicitly wants to
delete that credential too.

## Security boundary

- The bundle contains no Access Secret and does not forward one in argv.
- The MCP subprocess reads the existing per-user `zhihu-search` credential
  file created by `zhihu-search --save-token`.
- DSH treats the configured stdio command as trusted host code outside the
  agent sandbox. Review and pin bundle releases before installation.
- Local PDF upload and OAuth token exchange remain CLI/Python-only and are
  not exposed as model-callable tools.
