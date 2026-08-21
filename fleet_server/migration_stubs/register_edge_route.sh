#!/bin/sh
# Stub: write Caddy snippet and reload edge proxy.
set -eu
echo "fleet-migration-stub: register_edge_route migration=${FLEET_MIGRATION_ID:-} host=${FLEET_MIGRATION_ROUTE_HOST:-}"
echo "stub_ok: register_edge_route"
