# Builtin Forge Fleet requirement template `certificator_source_ingest_worker`.
# Build: POST /v1/container-templates/build (network for pip + Playwright — FLEET_TEMPLATE_BUILD_NETWORK).
#
# Job inputs use the agreed pack/unpack path: certificator uploads a gzip tar + manifest
# (PUT /v1/jobs/{id}/workspace). The image does *not* pip-install forge-certificators from
# git; it only ships a tiny stdlib entrypoint and PyPI wheels. Packaged `src/` on the
# workspace mount supplies `forge_certificators` modules (PYTHONPATH includes `./src`).
#
# Keep fleet_source_ingest_worker.py aligned with forge-certificators worker/fleet_source_ingest.py.
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# PyPI deps commonly imported by packed certificator source (no git clone / no project wheel).
RUN pip install --no-cache-dir \
    "httpx>=0.27.0" \
    "pydantic>=2.0" \
    "jinja2>=3.1.0" \
    "playwright>=1.40" \
    && playwright install chromium \
    && rm -rf /root/.cache/pip
COPY fleet_source_ingest_worker.py /app/fleet_source_ingest_worker.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/fleet_source_ingest_worker.py"]
