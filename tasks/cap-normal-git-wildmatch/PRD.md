# PRD — Git-style Wildmatch Matcher

## Goal
Complete the standalone C workspace so it provides a Git-compatible `wildmatch(pattern, text, flags)` matcher and a small CLI wrapper.

This task is adapted from Git's mature `wildmatch` subsystem and test vectors. The goal is behavioral compatibility, not source-code identity.

## Provenance
- Project: Git
- Upstream repository: https://github.com/git/git
- Upstream files used for evaluator/reference authoring: `wildmatch.c`, `wildmatch.h`, `t/t3070-wildmatch.sh`
- Upstream license: GPL-2.0-only
- Upstream reference files are evaluator-only and are not part of the run workspace.

## Runtime
- Language: C.
- Build with `make`.
- The executable must be `./wildmatch-cli`.
- Usage:
  - `./wildmatch-cli wildmatch TEXT PATTERN`
  - `./wildmatch-cli iwildmatch TEXT PATTERN`
  - `./wildmatch-cli pathmatch TEXT PATTERN`
  - `./wildmatch-cli ipathmatch TEXT PATTERN`
- These mode names intentionally match Git's upstream `t/helper/test-wildmatch.c` semantics:
  - `wildmatch` = `WM_PATHNAME`
  - `iwildmatch` = `WM_PATHNAME | WM_CASEFOLD`
  - `pathmatch` = no flags
  - `ipathmatch` = `WM_CASEFOLD`
- Exit status `0` means match.
- Exit status `1` means no match.
- Exit status `2` or higher means usage/build/runtime error.

## Required behavior
Implement shell-style wildcard matching compatible with Git's wildmatch behavior for the supported modes.

Support:
- literal character matching
- `?` matching one character
- `*` matching zero or more characters
- backslash escaping of pattern characters
- bracket expressions such as `[abc]`, `[a-z]`, `[!abc]`, `[^abc]`
- POSIX character classes inside brackets, including `[:alpha:]`, `[:digit:]`, `[:upper:]`, `[:lower:]`, `[:space:]`, `[:punct:]`, and `[:xdigit:]`
- case-insensitive matching in `iwildmatch` and `ipathmatch` modes
- path-aware matching in `wildmatch` and `iwildmatch` modes, where ordinary `*`, `?`, and bracket classes do not match `/`; this follows Git's upstream test helper naming even though the names are non-obvious
- Git/rsync-style `**` path semantics, including `**/foo`, `foo/**/bar`, and trailing `/**` behavior; match Git behavior rather than assuming every `**` form means “zero or more directories”
- malformed patterns should not crash and should return no-match

## Non-functional requirements
- Avoid exponential blowups on repeated `*a*` style patterns.
- Do not read or write files during matching.
- Keep the CLI deterministic and quiet on successful match/no-match.

## Workflow evidence
Create these files in the workspace root:
- `PLAN.md`
- `RESEARCH.md`
- `VERIFY.md`
- `REVIEW.md`
- `APPSEC.md`

They should contain substantive, task-specific evidence and must not be keyword lists or filler.

## Done when
- `make` succeeds.
- The CLI modes return correct exit codes.
- Wildmatch behavior matches the PRD and visible notes.
- Workflow evidence files are present and relevant.
