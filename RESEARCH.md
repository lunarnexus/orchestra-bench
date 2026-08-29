
## Slice 1.4 — Official harness installation research

Sources consulted:

- Hermes official installation guide: https://hermes-agent.nousresearch.com/docs/getting-started/installation
- Hermes official CLI reference: https://hermes-agent.nousresearch.com/docs/reference/cli-commands
- OpenCode official installation guide: https://opencode.ai/docs/
- OpenCode official config guide: https://opencode.ai/docs/config/

### Hermes

Official Linux command-line installation:

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

The official installer handles dependencies, repository clone, virtual environment, and the `hermes` command. In root mode it uses `/usr/local/lib/hermes-agent/` for code and `/usr/local/bin/hermes` for the command; per-user mode uses `~/.hermes/hermes-agent/` and `~/.local/bin/hermes`. Normal configuration is under `~/.hermes/`: secrets in `.env`, non-secret settings in `config.yaml`.

For the root-run benchmark container, root-mode installation and `/root/.hermes/` runtime/config paths match the documented layout. The Docker build should use the official installer in a cacheable install layer and must not silently copy host credentials into the image.

### OpenCode

Official v1 installation options include:

```bash
curl -fsSL https://opencode.ai/install | bash
# or
npm install -g opencode-ai
```

The current V2 Dockerfile already has Node/npm, so the documented npm installation is the simplest Docker build input. The official CLI is `opencode` (not the separate beta `opencode2` documented at `opencode.ai/v2`).

OpenCode configuration is JSON/JSONC and uses merged precedence. Documented locations include global `/root/.config/opencode/opencode.json`, project `opencode.json`, and a custom directory selected with `OPENCODE_CONFIG_DIR`. The project config tree should therefore override the container's global config through the documented custom-directory or global-config path, without inventing a new OpenCode format.

### Cache/install conclusion

The available evidence supports these implementation choices without guessing package identity:

- install Hermes with the official installer
- install OpenCode v1 with the official `opencode-ai` npm package
- keep both installations in cached Docker layers before the source/plugin cache-bust boundary
- apply project config overrides after installation, using each harness's documented paths
- keep Pi RPC/Orchestra lifecycle work deferred until the final feature phase, after ordinary harnesses, task/suite automation, and results management are working

Exact version pinning remains an implementation choice to resolve from project reproducibility requirements; do not claim a pinned version unless one is selected and recorded.
