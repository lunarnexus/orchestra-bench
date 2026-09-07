# orchestra-bench shared benchmark environment
FROM node:22-slim

LABEL org.opencontainers.image.description="orchestra-bench shared benchmark container"

ARG ORCHESTRA_REPO_URL="http://git.lunarnexus.local:3000/james/orchestra"
ARG PI_LMSTUDIO_PLUGIN_URL="http://git.lunarnexus.local:3000/james/pi-lmstudio"
ARG PI_CODEGRAPH_PLUGIN_URL="http://git.lunarnexus.local:3000/james/pi-codegraph"
ARG PI_WEB_TOOLS_PLUGIN_URL="http://git.lunarnexus.local:3000/james/pi-web-tools"

ENV ORCHESTRA_HOME=/opt/orchestra
ENV PYTHONPATH=/opt/orchestra-bench

RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl ca-certificates openssh-client python3 python3-pip python3-venv ruby ruby-dev build-essential libsqlite3-dev pkg-config && \
    rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --break-system-packages --no-cache-dir fastapi uvicorn pytest httpx django pyyaml
RUN npm install -g @earendil-works/pi-coding-agent@latest express
RUN curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
RUN npm install -g opencode-ai
ENV NODE_PATH=/usr/local/lib/node_modules:/usr/lib/node_modules
RUN gem install --no-document sinatra sqlite3 rack-test minitest

ARG SOURCE_PLUGIN_CACHE_BUST="manual"

RUN echo "source/plugin cache bust: $SOURCE_PLUGIN_CACHE_BUST" && \
    git clone "$ORCHESTRA_REPO_URL" "$ORCHESTRA_HOME/src" && \
    python3 -m venv "$ORCHESTRA_HOME/.venv" && \
    . "$ORCHESTRA_HOME/.venv/bin/activate" && \
    python3 -m pip install --upgrade pip && \
    python3 -m pip install -e "/opt/orchestra/src[dev]"

ENV PATH="/opt/orchestra/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

RUN pi install "$PI_LMSTUDIO_PLUGIN_URL"
#RUN pi install "$PI_CODEGRAPH_PLUGIN_URL"
#RUN pi install "$PI_WEB_TOOLS_PLUGIN_URL"

ENV BENCH_TASKS=/bench/task-materials-source \
    BENCH_RESULTS=/bench/results \
    BENCH_ARTIFACTS=/bench/artifacts \
    BENCH_WORKSPACE=/workspace \
    BENCH_ORCHESTRA_CONFIG_SRC=/bench/orchestra-config \
    BENCH_PI_CONFIG_SRC=/bench/pi \
    BENCH_HERMES_CONFIG_SRC=/bench/hermes \
    BENCH_OPENCODE_CONFIG_SRC=/bench/opencode \
    BENCH_PI_SKILLS_SRC=/bench/skills \
    BENCH_ORCHESTRA_EXTENSION_SRC=/bench/orchestra-extension \
    PI_HERMES_RUNTIME_DIR=/root/.hermes \
    PI_OPENCODE_RUNTIME_DIR=/root/.config/opencode

RUN mkdir -p "$BENCH_TASKS" "$BENCH_RESULTS" "$BENCH_ARTIFACTS" "$BENCH_WORKSPACE" /bench/orchestra-config /bench/skills /bench/pi /bench/hermes /bench/opencode /root/.pi/agent /root/.hermes /root/.config/opencode

COPY bench/ /opt/orchestra-bench/bench/
COPY docker/entrypoint.sh /usr/local/bin/bench-entrypoint
RUN chmod +x /usr/local/bin/bench-entrypoint

ENTRYPOINT ["/usr/local/bin/bench-entrypoint"]
