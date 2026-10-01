# Skill evaluation

`trigger-evals.json` tests whether a request should activate the Skill at all.

## Offline structural checks

```bash
uv run pytest tests/test_skill_metadata.py
```

These checks validate metadata, copied-install references, shell-example structure, and
fixture shape/coverage. They do **not** run a model or demonstrate a behavioral pass rate.
They do not call the Zhihu API or consume business quota.

## Trigger evaluation in a target agent

Use a fresh context with the candidate Skill installed. For each case, present the query
without manually selecting the Skill and record whether it activates. Check both false
positives (especially source restrictions and supplied text) and false negatives (account,
question, and setup capabilities). If a run needs tool calls, use mocked tool results; do
not execute account mutations or send real secrets.

Report model/client version, candidate commit, and per-case outcomes. Compare baseline and
candidate using the same model and settings. Do not publish an accuracy/improvement
percentage from structural checks or unexecuted fixtures.
