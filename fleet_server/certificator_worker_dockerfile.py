"""Bootstrap Dockerfile for the auto-provisioned certificator source-ingest Fleet worker."""

from __future__ import annotations

# Built on the Forge Fleet host (requires outbound git + PyPI during ``docker build``).
# Override this row in ``requirement_templates.json`` or set ``FORGE_FLEET_SOURCE_INGEST_TEMPLATE_REQUIREMENTS``
# on the certificator when you publish a prebuilt image instead.
CERTIFICATOR_SOURCE_INGEST_WORKER_TEMPLATE_ID = "forge_certificator_source_ingest_worker"

CERTIFICATOR_SOURCE_INGEST_WORKER_DOCKERFILE = r"""# Auto-provisioned by Forge Fleet — source-ingest worker (Playwright + subprocess argv bundle).
FROM python:3.12-slim
ARG FORGE_CERTIFICATORS_GIT=https://github.com/autowww/forge-certificators.git
ARG FORGE_CERTIFICATORS_REF=main
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "forge-certificators[prepcast] @ git+${FORGE_CERTIFICATORS_GIT}@${FORGE_CERTIFICATORS_REF}" \
    && python -m playwright install chromium \
    && rm -rf /root/.cache/pip
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "forge_certificators.worker.fleet_source_ingest"]
"""
