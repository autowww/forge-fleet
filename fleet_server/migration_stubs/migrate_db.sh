#!/bin/sh
# Fallback stub — Fleet prefers recipe meta.migrate_argv in the app image.
set -eu
echo "fleet-migration: migrate_db stub (recipe migrate_argv missing) migration=${FLEET_MIGRATION_ID:-}"
test -d /migration/bundle || { echo "bundle_mount_missing"; exit 2; }
echo "migrate_db_requires_recipe_migrate_argv"
exit 2
