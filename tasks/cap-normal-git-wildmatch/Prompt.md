# Run Prompt
Read `PRD.md`, inspect the fixture and KB files, and finish the Git-style wildmatch workspace.
Dispatch and proceed until finished.

Requirements:
- implement `wildmatch.c` so `make` builds `./wildmatch-cli`
- support all four CLI modes exactly as Git's upstream `test-wildmatch` helper names them: `wildmatch`, `iwildmatch`, `pathmatch`, `ipathmatch`
- match Git-style wildcard, bracket, escape, casefold, pathname, and `**` behavior described in `PRD.md` and `kb/upstream-notes.md`
- add `PLAN.md`, `RESEARCH.md`, `VERIFY.md`, `REVIEW.md`, and `APPSEC.md` with substantive, task-specific evidence; do not use keyword lists or filler
- keep the workspace runnable without evaluator-only files

Do not leave background processes running at the end.
