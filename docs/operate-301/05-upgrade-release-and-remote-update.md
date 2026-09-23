# Operate 301 — Upgrade, release, and remote self-update

This page ties together **semver shipping**, **bare-metal refresh**, **cooperative lifecycle upgrades**, and the authenticated admin upgrade paths.

## Cooperative upgrade (preferred)

**`POST /v1/admin/upgrade`** runs the lifecycle coordinator before any restart:

| Step | Action |
|------|--------|
| 1 | Fleet `draining=true`; pause new jobs and app-gateway proxy admissions |
| 2 | `POST …/prepare-stop` on loopback dependents |
| 3 | Poll `GET …/stop-readiness` until clear or **`max_wait_sec`** |
| 4 | Route by **`install_channel`**: git pull or apt signal queue |
| 5 | Poll **`GET /v1/admin/upgrade/status`** (apt) or wait for Fleet health (git) |

| Mode | Default wait | Target downtime |
|------|--------------|-----------------|
| `update` | 10s | ≤10s Fleet HTTP unavailable |
| `upgrade` | 45s | ≤60s end-to-end (apt timer granularity) |

On timeout with `on_timeout=abort`: **409** `upgrade_blocked` and **`waiting_on[]`** blockers. With `on_timeout=force`, Fleet proceeds anyway.

**Apt channels:** Fleet writes **`upgrade-request.json`**; **`forge-fleet-apt-upgrade.timer`** (every minute) runs **`scripts/apt-upgrade-cron.sh`**. No stored password — one-time timer enable at install/migrate.

CLI: **`land-fleet upgrade --wait`**, **`land-fleet timer-status`**, **`land-fleet migrate-to-apt`**.

See [fleet-lifecycle-contract](../design/fleet-lifecycle-contract.md) and [migrate-installations-to-apt](../operate/migrate-installations-to-apt.md).

## Local maintainer workstation — ship Fleet

`./scripts/update-fleet.sh` (repo root):

- **`git submodule update --init --recursive`**, SemVer bump, commit **`chore(release)`**, **`git push`**
- optional **`sudo ./install-update.sh`** or **`./update-user.sh`** after push (layout-dependent)
- optional **`--remote-git-self-update`** → **`curl` POST** **`{FORGE_FLEET_BASE_URL}/v1/admin/git-self-update`** with bearer

Env hints: **`FORGE_FLEET_BASE_URL`**, **`FORGE_FLEET_BEARER_TOKEN`**, **`FLEET_REMOTE_GIT_SELF_UPDATE_URL`**. Overrides: **`--remote-url`**, **`--remote-bearer`**.

## Remote Fleet host semantics

Fleet must know **`FLEET_GIT_ROOT`** (tree with **`.git`**) for git-channel self-update. **`/opt/forge-fleet`** git installs may reply **400** with **`system_root_install_command`** — migrate to **`apt_system`** per runbook.

After **apt_system** migration, routine remote bumps use **`POST /v1/admin/upgrade`** on the host bearer (not git pull).

## Operators refreshing “this laptop” Fleet

**Git user path:** **`git pull --rebase`** in **`~/forge-fleet`**, **`./update-user.sh`**, **`systemctl --user restart forge-fleet.service`**.

**Apt user path:** admin **Update Fleet** or **`POST /v1/admin/upgrade`** + **`land-fleet upgrade --wait`**.

Workspace rules (“update service”) refresh localhost Fleet without semver release unless combined intentionally.

See also **[Architecture](03-architecture.md)** for systemd layout and **[HTTP API](../reference/01-http-api-reference.md)** for upgrade response schemas.
