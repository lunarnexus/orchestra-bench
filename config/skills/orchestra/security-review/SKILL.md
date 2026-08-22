---
name: security-review
description: Review software changes for security risks across auth, data, secrets, injection, dependencies, filesystem, shell, network, and agent boundaries.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [software-engineering, security, devsecops, review]
    related_skills: [review-code, verify-work]
---

# Security Review

Use this skill during planning for risky work and near the end before ship. Security is part of the lifecycle, not a last-minute vibe check.

Professional goal: identify material, exploitable risks and practical fixes.

## Security-sensitive triggers

Review carefully when changes touch:
- authentication or authorization
- secrets, tokens, credentials
- user input or untrusted data
- file paths or filesystem writes
- shell commands or subprocesses
- network requests or URLs
- database queries
- serialization/deserialization
- logs, telemetry, snapshots, fixtures
- dependencies or package updates
- cryptography
- agent/tool prompt boundaries
- permissions or sandboxing

## Baseline categories

Use OWASP/CWE-style thinking. Check:
- broken access control
- cryptographic failures / sensitive data exposure
- injection: SQL, command, template, path, XSS, SSRF, prompt injection
- insecure design
- security misconfiguration
- vulnerable/outdated dependencies
- identification/authentication failures
- software/data integrity failures
- logging/monitoring gaps for sensitive paths
- unsafe deserialization
- unsafe file/shell/network use

## Method

1. Understand the feature and trust boundaries.
2. Inspect the diff and relevant surrounding code.
3. Identify attacker-controlled inputs.
4. Trace data flow to sensitive sinks.
5. Check validation, encoding, authorization, and error handling.
6. Look for secrets in source, fixtures, logs, snapshots, generated files.
7. Check dependencies and configuration changes.
8. Filter false positives with evidence.
9. Report material risks with practical remediations.

## Static scan prompts

For added lines, look for:
- hardcoded secrets or tokens
- `eval`, `exec`, dynamic import/load
- shell command construction
- SQL string formatting
- path joins with untrusted input
- URL fetches from untrusted input
- unsafe YAML/pickle/deserialization
- logging sensitive values
- permission checks removed or weakened

## Finding format

```md
- HIGH — `file:line` — category — issue
  Impact: <exploit path or damage>
  Evidence: <code/diff/source>
  Recommendation: <fix>
```

Severity:
- **HIGH**: plausible exploit, credential/data exposure, auth bypass, command execution.
- **MEDIUM**: meaningful hardening gap or risky pattern with constraints.
- **LOW**: defense-in-depth or informational concern.

## Output

```md
## Security Review Report

Verdict:
- pass / fail / pass with notes

Findings:
- ...

Sensitive areas inspected:
- ...

Checks/evidence:
- ...

Missing checks:
- ...

Residual risk:
- ...
```
