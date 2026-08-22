# Upstream notes — Git wildmatch

Provenance:
- Project: Git
- Source behavior: `wildmatch.c` / `wildmatch.h`
- Upstream tests: `t/t3070-wildmatch.sh`
- Upstream repository: https://github.com/git/git
- License: GPL-2.0-only

Important behavior notes:
- CLI mode names intentionally follow Git's `t/helper/test-wildmatch.c`, not intuitive names.
- `wildmatch` uses `WM_PATHNAME`.
- `iwildmatch` uses `WM_PATHNAME | WM_CASEFOLD`.
- `pathmatch` uses no flags.
- `ipathmatch` uses `WM_CASEFOLD`.
- In pathname mode, `**` has special directory-crossing behavior.
- A trailing `**` can match across slash boundaries.
- A single `*` before a slash matches at most one path component.
- Malformed bracket expressions should fail safely, not crash.
