# Run Prompt
Read `PRD.md`, inspect the fixture and KB files, and finish the OpenSSH-style config resolver workspace.
Dispatch and proceed until finished.

Requirements:
- implement `ssh_config_resolve.py` so it resolves the supported OpenSSH client config subset and matches `ssh -G -F CONFIG HOST` behavior for that subset
- support Host blocks, wildcard/negated patterns, first-value-wins precedence, additive IdentityFile, Include files, quoting/comments, booleans, ports, and `%` token expansion
- output the JSON fields specified in `PRD.md`
- add `PLAN.md`, `RESEARCH.md`, `VERIFY.md`, `REVIEW.md`, and `APPSEC.md` with substantive, task-specific evidence; do not use keyword lists or filler
- keep the workspace runnable without evaluator-only files

Do not leave background processes running at the end.
