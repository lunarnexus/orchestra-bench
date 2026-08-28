# PRD — OpenSSH-style Client Config Resolver

## Goal
Complete a standalone `ssh_config_resolve.py` tool that resolves a useful subset of OpenSSH client configuration behavior.

This task is adapted from OpenSSH's mature client config parser (`readconf.c`) and regress tests. Behavioral compatibility matters more than matching source code. For the supported subset, the behavioral oracle is `ssh -G -F CONFIG HOST` from OpenSSH.

## Provenance
- Project: OpenSSH portable
- Upstream repository: https://github.com/openssh/openssh-portable
- Upstream files used for evaluator/reference authoring: `readconf.c`, `regress/cfgmatch.sh`
- Upstream license: BSD-style/OpenSSH portable licenses
- Upstream reference files are evaluator-only and are not part of the run workspace.

## Runtime
- Language: Python 3.
- Executable: `python3 ssh_config_resolve.py --config CONFIG --host HOST`.
- Output: one JSON object on stdout.
- Exit non-zero with a clear stderr message for invalid config syntax and include cycles. Match OpenSSH behavior for missing include globs/files in this supported subset.

## Required output fields
The JSON object must include these keys. Values should match OpenSSH `ssh -G -F CONFIG HOST` for the supported subset, normalized into JSON:
- `host` — query host passed on the CLI
- `hostname` — resolved `HostName`, defaulting to the query host if unset
- `user` — effective `user` from `ssh -G`
- `port` — effective integer `port` from `ssh -G`
- `identityfile` — effective `identityfile` list from `ssh -G`, including OpenSSH defaults when no active `IdentityFile` overrides them
- `proxycommand` — effective raw `proxycommand` string from `ssh -G`, or `null`/missing when unset
- `forwardagent` — effective `forwardagent` as a boolean
- `compression` — effective `compression` as a boolean

## Required config semantics
Support OpenSSH-style client config behavior for this subset:

### Parsing
- Ignore blank lines and comments.
- Comments begin with `#` outside quotes.
- Keywords are case-insensitive.
- Support both `Keyword value` and `Keyword=value`.
- Support single and double quoted values.
- Preserve spaces inside quoted `ProxyCommand` values.
- Report invalid lines instead of silently ignoring malformed syntax.

### Host blocks
- `Host` starts a host-specific block.
- A `Host` line contains one or more patterns.
- Patterns use shell-style wildcards: `*`, `?`, and bracket classes.
- A pattern prefixed by `!` negates the match.
- A host block is active when at least one positive pattern matches and no negated pattern matches.
- Global options before the first `Host` always apply.

### Precedence
Follow OpenSSH client config precedence for this task:
- Files are processed top-to-bottom.
- The first value obtained for a scalar option wins.
- Therefore host-specific blocks should appear before later defaults.
- `IdentityFile` is additive: every active `IdentityFile` line appends to the list.

### Include
- Support `Include PATH` lines.
- Relative include paths are resolved relative to the including config file.
- Glob includes are expanded in sorted order.
- Included files are processed at the point of the `Include` directive.
- Detect include cycles and fail clearly.

### Value handling
- `Port` must be an integer from 1 to 65535.
- Booleans accept `yes/no`, `true/false`, `on/off`, `1/0`.
- Match OpenSSH `ssh -G` output for `%` token handling in this subset. In particular, `HostName default-%h` resolves `%h` in `hostname`, while `ProxyCommand` should be reported as the raw effective string shown by `ssh -G` rather than pre-expanded by your tool.
- Do not expand environment variables or run shell commands.

## Workflow evidence
Create these files in the workspace root:
- `PLAN.md`
- `RESEARCH.md`
- `VERIFY.md`
- `REVIEW.md`
- `APPSEC.md`

They should contain substantive, task-specific evidence and must not be keyword lists or filler.

## Done when
- The CLI resolves configs correctly.
- It handles includes, precedence, negation, quoting, booleans, and invalid syntax.
- It is compatible with `ssh -G -F CONFIG HOST` behavior for the supported subset.
- Workflow evidence files are present and relevant.
