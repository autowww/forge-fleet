#!/bin/sh
# Fallback stub — Fleet prefers host ``docker compose up`` from recipe compose_root.
set -eu
echo "fleet-migration-stub: deploy_service migration=${FLEET_MIGRATION_ID:-} service=${FLEET_MIGRATION_SERVICE_ID:-}"
echo "deploy_service_requires_recipe_compose_root"
exit 2
