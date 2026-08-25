#!/bin/sh
# Copy migration bundle files into the recipe-named data volume (generic).
set -eu
echo "fleet-migration: seed_volume migration=${FLEET_MIGRATION_ID:-} step=${FLEET_MIGRATION_STEP_ID:-} volume=${FLEET_MIGRATION_VOLUME_NAME:-}"
test -d /migration/bundle || { echo "bundle_mount_missing"; exit 2; }
test -d /seed-target || { echo "seed_target_missing"; exit 2; }
if [ -d /migration/bundle/data ]; then
  cp -a /migration/bundle/data/. /seed-target/
else
  cp -a /migration/bundle/. /seed-target/
fi
rm -f /seed-target/.forge_migration_manifest.json
echo "seed_ok"
