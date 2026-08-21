#!/bin/sh
# Stub: copy corpus tree from /migration/bundle into a named Docker volume.
set -eu
echo "fleet-migration-stub: seed_corpus_volume migration=${FLEET_MIGRATION_ID:-} step=${FLEET_MIGRATION_STEP_ID:-}"
test -d /migration/bundle || { echo "bundle_mount_missing"; exit 2; }
echo "stub_ok: seed_corpus_volume"
