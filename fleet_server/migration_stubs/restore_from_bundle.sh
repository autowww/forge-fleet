#!/bin/sh
# Stub: rollback — restore volumes and DB state from the uploaded bundle.
set -eu
echo "fleet-migration-stub: restore_from_bundle migration=${FLEET_MIGRATION_ID:-} step=${FLEET_MIGRATION_STEP_ID:-}"
test -d /migration/bundle || { echo "bundle_mount_missing"; exit 2; }
echo "stub_ok: restore_from_bundle"
