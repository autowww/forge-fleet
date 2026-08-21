#!/bin/sh
# Stub: register or start a managed compose service via Fleet-side hooks.
set -eu
echo "fleet-migration-stub: deploy_service migration=${FLEET_MIGRATION_ID:-} service=${FLEET_MIGRATION_SERVICE_ID:-}"
echo "stub_ok: deploy_service"
