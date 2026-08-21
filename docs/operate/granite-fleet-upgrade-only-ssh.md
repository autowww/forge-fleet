# Granite — Fleet upgrade (SSH exception only)

When refreshing Forge Fleet on Granite, use the **Fleet API first**. SSH is allowed **only** to upgrade the Fleet daemon when the API cannot complete the update.

## Preferred (no SSH)

From a maintainer workstation with Fleet credentials:

```bash
cd forge-fleet
./scripts/update-fleet.sh --remote-git-self-update
```

Or direct API:

```bash
curl -sS -X POST "${FORGE_FLEET_BASE_URL}/v1/admin/git-self-update" \
  -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## SSH fallback (Fleet binary only)

Use SSH **only** when `git-self-update` returns `system_install_requires_root` or the user unit refresh fails and the host operator must run the documented install script:

```bash
cd ~/forge-fleet && git pull --ff-only && ./update-user.sh
```

**Do not** use SSH for Market Studio deploy, data bundles, `docker compose`, volume copies, or Caddy edits. Those flows use Fleet migration and container-service APIs (see [Granite Market Studio cutover](granite-market-studio-cutover.md)).

See also [Granite operator boundary](../design/granite-operator-boundary.md).
