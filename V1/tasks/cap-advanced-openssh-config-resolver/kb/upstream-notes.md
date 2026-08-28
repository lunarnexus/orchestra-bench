# Upstream notes — OpenSSH client config

Provenance:
- Project: OpenSSH portable
- Source behavior: `readconf.c`
- Regression/oracle area: OpenSSH `regress` config tests and `ssh -G -F` effective-config output
- Upstream repository: https://github.com/openssh/openssh-portable
- License: BSD-style/OpenSSH portable licenses

Important behavior notes from OpenSSH's config parser:
- Config is processed in order.
- Any scalar value is only changed the first time it is set.
- Host-specific declarations should usually appear before defaults.
- `Host` patterns can include negation with `!`.
- `Include` is processed where it appears, not after the whole file.
- This benchmark only asks for a documented subset, not the full OpenSSH parser.
- For that subset, evaluator cases compare the candidate JSON output directly against normalized `ssh -G -F CONFIG HOST` output.
