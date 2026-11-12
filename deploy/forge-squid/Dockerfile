FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY vendor/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Vendored Python packages (synced from git by scripts/sync-forge-squid.sh)
COPY vendor/forge_dcs /app/forge_dcs
COPY vendor/forge_squid /app/forge_squid
COPY vendor/skills /app/skills

RUN useradd --system --uid 10001 --create-home forge \
 && mkdir -p /var/lib/forge-dcs/store /var/lib/forge-squid/cache \
 && chown -R forge:forge /var/lib/forge-dcs /var/lib/forge-squid /app
USER forge
ENV PYTHONPATH=/app
