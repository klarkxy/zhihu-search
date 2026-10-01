# Skill evaluation

These fixtures test two different questions:

- `trigger-evals.json`: should this request activate the Skill at all?
- `workflow-evals.json`: after activation, which action and safeguards are appropriate?

## Offline structural checks

```bash
uv run pytest tests/test_skill_metadata.py
```

These checks validate metadata, copied-install references, shell-example structure, and
fixture shape/coverage. They do **not** run a model or demonstrate a behavioral pass rate.
They do not call the Zhihu API or consume business quota.

## Behavioral evaluation in a target agent

Use a fresh context with the candidate Skill installed. For each trigger case, present the
query without manually selecting the Skill and record whether it activates. Check both
false positives (especially source restrictions and supplied text) and false negatives
(account, question, and setup capabilities).

For each workflow case, supply its `query` and simulated tool/environment `context`.
Use mocked tool results matching that context; do not execute account mutations or send
real secrets merely to evaluate instructions. Record the first action, subsequent calls,
and final response. `expected_first_action` refers to the action from the stated context,
which may already include a completed first search, failed upload, or credential check.
An explanatory response counts as `explain_limitation`; hyphenated CLI commands and
underscore MCP equivalents count as the same operation. `other_enable` means the visible
`other(action="enable")` call followed by discovery, not a new CLI command.

A case passes only if the expected action is appropriate, every `must` is met, and no
`must_not` behavior occurs. Review the actual trace, not merely the agent's claim of
compliance. Report model/client version, candidate commit, per-case outcomes and failures.
Compare baseline and candidate using the same model, settings, and mocked inputs. Do not
publish an accuracy/improvement percentage from structural checks or unexecuted fixtures.
