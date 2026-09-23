# Learn 101 — Migrate to apt

**Outcome:** move an existing **git** Fleet install to the **apt** channel with cooperative upgrades.

**Prerequisite:** [Operator apt install](09-operator-apt-install.md) or an existing git install you want to replace.

## Check current channel

```bash
curl -fsS -H "Authorization: Bearer ${FLEET_BEARER_TOKEN}" \
  http://127.0.0.1:18766/v1/admin/install-channel | jq .
```

Or:

```bash
land-fleet migrate-to-apt --user    # laptop
land-fleet migrate-to-apt --system  # Granite / system unit
```

## Laptop (git_user → apt_user)

1. Save env: bearer token, remote peers, `forge-fleet.env` conffile if present.
2. Install user package (one-time sudo):

```bash
curl -fsSL "${FORGE_APT_BASE_URL:-https://packages.forgesdlc.com/fleet/ubuntu}/install.sh" \
  -o /tmp/forge-fleet-install.sh
bash /tmp/forge-fleet-install.sh --user --migrate-from-git
land-fleet setup-user
```

3. Confirm timer: `land-fleet timer-status` → `forge-fleet-apt-upgrade.timer` **active**.
4. Upgrade from admin **Update Fleet** or:

```bash
curl -fsS -X POST -H "Authorization: Bearer ${FLEET_BEARER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"mode":"upgrade","max_wait_sec":45}' \
  http://127.0.0.1:18766/v1/admin/upgrade
land-fleet upgrade --wait
```

## System host (git_system → apt_system)

Follow the runbook in **[Migrate installations to apt](../operate/migrate-installations-to-apt.md)** (Granite section). After migration, use **`POST /v1/admin/upgrade`** instead of **`git-self-update`** for routine bumps.

## See also

- [Upgrade, release, and remote update](../operate-301/05-upgrade-release-and-remote-update.md)
- [Fleet lifecycle contract](../design/fleet-lifecycle-contract.md)
