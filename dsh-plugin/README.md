# dsh-plugin-zhihu-search

DeepSeek Harness bundle for
[`zhihu-search`](https://github.com/klarkxy/zhihu-search). It mounts the
same `zhihu-search` Skill into the target profile. Queries still run as
on-demand `uvx zhihu-search` commands. The bundle does not start an MCP
server or store credentials in DSH config.

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

Plugin-search tools and DSH marketplaces index the GitHub topic
`dsh-plugin`. That topic lives on the repository About page, not in this
tree; `package.json` keywords do not publish it.

Stop and restart the profile after a persistent install. The Skill catalog
should then include `zhihu-search`. The agent loads that Skill and runs the
narrowest `uvx zhihu-search` command. It reuses a matching Zhihu MCP tool
only when some other client already exposed one.

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

Removing the bundle unmounts the profile-shipped Skill. It does not remove
an independently installed copy under `~/.agents/skills`, and it does not
remove the Python credential file. Use `uvx zhihu-search --clear-token`
only when the user explicitly wants to delete that credential too.

If a same-named Skill already exists in the project or user skill roots,
that nearer copy wins. Update or remove that copy if you want the
bundle-shipped Skill to take effect.

## Security boundary

- The bundle contains no Access Secret and does not forward one in argv.
- CLI calls read the existing per-user `zhihu-search` credential file
  created by `zhihu-search --save-token`.
- Never paste an Access Secret, OAuth app key, or OAuth token into chat.
- Local PDF / knowledge-base upload and OAuth token exchange remain
  CLI/Python-only and are not exposed as model-callable tools.
