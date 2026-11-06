FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY vendor/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Vendored Python packages (synced from git working trees by scripts/sync-forge-2b-poc.sh)
COPY vendor/forge_dcs /app/forge_dcs
COPY vendor/forge_2b /app/forge_2b
COPY vendor/skills /app/skills

RUN useradd --system --uid 10001 --create-home forge \
 && mkdir -p /var/lib/forge-dcs/store /var/lib/forge-2b/cache \
 && chown -R forge:forge /var/lib/forge-dcs /var/lib/forge-2b /app
USER forge
ENV PYTHONPATH=/app
