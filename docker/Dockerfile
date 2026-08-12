# orchestra-bench shared benchmark environment
FROM node:22-slim

LABEL org.opencontainers.image.description="orchestra-bench shared benchmark container"

ARG ORCHESTRA_REPO_URL="http://git.lunarnexus.local:3000/james/orchestra"
ARG PI_LMSTUDIO_PLUGIN_URL="http://git.lunarnexus.local:3000/james/pi-lmstudio"
ARG PI_CODEGRAPH_PLUGIN_URL="http://git.lunarnexus.local:3000/james/pi-codegraph"
ARG PI_WEB_TOOLS_PLUGIN_URL="http://git.lunarnexus.local:3000/james/pi-web-tools"

ENV ORCHESTRA_HOME=/opt/orchestra

# Runtime deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl ca-certificates python3 python3-pip python3-venv ruby ruby-dev build-essential libsqlite3-dev pkg-config && \
    rm -rf /var/lib/apt/lists/*

# Preinstall common Python app/task deps for capability workloads.
RUN python3 -m pip install --break-system-packages --no-cache-dir fastapi uvicorn pytest httpx django

# Install Pi coding agent and practical Node task deps.
RUN npm install -g @earendil-works/pi-coding-agent@latest express
ENV NODE_PATH=/usr/local/lib/node_modules:/usr/lib/node_modules

# Preinstall common Ruby app/task deps for capability workloads.
RUN gem install --no-document sinatra sqlite3 rack-test minitest

# Apply benchmark-local Pi settings before plugin install, without clobbering
# unrelated Pi defaults/settings.
COPY config/pi/settings.json /tmp/bench-pi-settings.json
RUN mkdir -p /root/.pi/agent && \
    python3 - <<'PY'
import json
from pathlib import Path
source = Path('/tmp/bench-pi-settings.json')
target = Path('/root/.pi/agent/settings.json')
base = json.loads(target.read_text()) if target.exists() else {}
patch = json.loads(source.read_text()) if source.exists() else {}
base.update(patch)
target.write_text(json.dumps(base, indent=2) + '\n')
PY

# Copy benchmark-local Pi skills into the container runtime.
COPY config/skills/ /tmp/bench-skills/
RUN mkdir -p /root/.pi/agent/skills && \
    cp -a /tmp/bench-skills/. /root/.pi/agent/skills/

# Install Orchestra from source using the README dev flow.
RUN git clone "$ORCHESTRA_REPO_URL" "$ORCHESTRA_HOME/src" && \
    python3 -m venv "$ORCHESTRA_HOME/.venv" && \
    . "$ORCHESTRA_HOME/.venv/bin/activate" && \
    python3 -m pip install --upgrade pip && \
    python3 -m pip install -e "/opt/orchestra/src[dev]"

ENV PATH="/opt/orchestra/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Install Pi plugins via the official Pi command.
RUN pi install "$PI_LMSTUDIO_PLUGIN_URL" && \
    pi install "$PI_CODEGRAPH_PLUGIN_URL" 
#    pi install "$PI_WEB_TOOLS_PLUGIN_URL"

# Working dirs — these are the mount points for the host volumes
ENV BENCH_TASKS=/bench/tasks \
    BENCH_RESULTS=/bench/results \
    BENCH_ARTIFACTS=/bench/artifacts \
    BENCH_WORKSPACE=/workspace

RUN mkdir -p "$BENCH_TASKS" "$BENCH_RESULTS" "$BENCH_ARTIFACTS" "$BENCH_WORKSPACE"

COPY docker/entrypoint.sh /usr/local/bin/bench-entrypoint
RUN chmod +x /usr/local/bin/bench-entrypoint

ENTRYPOINT ["/usr/local/bin/bench-entrypoint"]
