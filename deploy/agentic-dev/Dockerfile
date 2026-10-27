# forge_agentic_dev — ephemeral container for one approved repo task.
# Built on the Fleet host by fleet_server.agentic_dev_job (no SSH, no laptop copy).
# Contents: git, python3, node (for the Cursor CLI), cursor-agent pinned by CURSOR_AGENT_VERSION.
FROM debian:bookworm-slim

ARG CURSOR_AGENT_VERSION=latest
ARG NODE_MAJOR=22

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PATH=/home/forge/.local/bin:/usr/local/bin:/usr/bin:/bin

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git python3 python3-venv bash jq xz-utils \
 && rm -rf /var/lib/apt/lists/*

# Node for the Cursor CLI runtime and for repos whose verify step needs it.
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 --shell /bin/bash forge
USER forge
WORKDIR /home/forge

# Cursor CLI. The official installer places cursor-agent under ~/.local/bin.
# CURSOR_AGENT_VERSION is recorded in the image label; "latest" is resolved at build time.
RUN curl -fsSL https://cursor.com/install | bash \
 && /home/forge/.local/bin/cursor-agent --version > /home/forge/.cursor-agent-version 2>&1 || true

COPY --chown=forge:forge run_task.py /opt/forge/run_task.py

LABEL org.forgesdlc.template="forge_agentic_dev" \
      org.forgesdlc.cursor_agent_version="${CURSOR_AGENT_VERSION}"

# Task contract: /task/task.json (ro), /out (rw), env CURSOR_API_KEY + GIT_TOKEN.
ENTRYPOINT ["python3", "/opt/forge/run_task.py"]
