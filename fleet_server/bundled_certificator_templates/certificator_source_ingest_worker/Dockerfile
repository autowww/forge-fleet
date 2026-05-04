# Builtin Forge Fleet requirement template `certificator_source_ingest_worker`:
# certificator queues jobs with meta.use_fleet_template_image; Fleet builds via
# POST /v1/container-templates/build (needs git + pip network — see FLEET_TEMPLATE_BUILD_NETWORK).
#
# Override with PUT /v1/container-templates or rsync a COPY-based Dockerfile from the
# forge-certificators repo if GitHub must stay private.
ARG FORGE_CERTIFICATORS_GIT_REF=main
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN pip install --no-cache-dir \
    "forge-certificators[prepcast] @ git+https://github.com/autowww/forge-certificators.git@${FORGE_CERTIFICATORS_GIT_REF}" \
    && playwright install chromium \
    && rm -rf /root/.cache/pip
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "forge_certificators.worker.fleet_source_ingest"]
