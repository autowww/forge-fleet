#!/bin/sh
# Stub: sqlite → postgres migration using bundle SQL dumps.
set -eu
echo "fleet-migration-stub: migrate_db migration=${FLEET_MIGRATION_ID:-} step=${FLEET_MIGRATION_STEP_ID:-}"
test -d /migration/bundle || { echo "bundle_mount_missing"; exit 2; }
echo "stub_ok: migrate_db"
