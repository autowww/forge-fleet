# Migrate Fleet installations to apt

Move **git_user** / **git_system** hosts to **`apt_user`** / **`apt_system`** so routine upgrades use cooperative lifecycle + apt (or git-user `update-user.sh`) instead of ad-hoc git pulls.

## Install channels

| Channel | Typical layout | Routine upgrade |
|---------|----------------|-----------------|
| `git_user` | `~/forge-fleet` → `~/.local/share/forge-fleet`, user systemd **:18766** | `POST /v1/admin/upgrade` → git pull + restart (no root) |
| `apt_user` | `/usr/lib/forge-fleet`, user systemd | Admin upgrade → signal file → **root timer** (~60s) |
| `git_system` | `/opt/forge-fleet` + `FLEET_GIT_ROOT`, system unit **:18765** | SSH/sudo git path (legacy) |
| `apt_system` | `/opt/forge-fleet` from `forge-fleet` deb | Admin upgrade → signal → root timer |

Detect with **`GET /v1/admin/install-channel`** or **`land-fleet migrate-to-apt`**.

## Mercury (laptop) — git_user → apt_user

1. Export bearer + remote peer settings from `~/.config/forge-fleet/` or env.
2. One-time sudo: `bash install.sh --user --with-docker` from Fleet apt repo (see [learn-101/09](../learn-101/09-operator-apt-install.md)).
3. `land-fleet setup-user` — refresh user unit against `/usr/lib/forge-fleet`.
4. Verify: `curl -fsS http://127.0.0.1:18766/v1/health` and remote Granite peer if configured.
5. `land-fleet migrate-to-apt --user` — checklist (apt source, package, unit path, timer).
6. Disable legacy unit if it still points only at `~/.local/share/forge-fleet`.
7. Optional: keep git clone for contributions; set `FLEET_INSTALL_CHANNEL=apt_user` in env after migration.

## Granite — git_system → apt_system

1. **`POST /v1/admin/snapshot`** backup (settings, peers, jobs summary).
2. Prefer Fleet HTTP paths per [granite-operator-boundary](../design/granite-operator-boundary.md). One bounded operator window may be required for first apt bootstrap.
3. `sudo bash install.sh --system --with-docker` on host.
4. `land-fleet migrate-to-apt --system`.
5. Routine bumps: **`POST /v1/admin/upgrade`** (replaces routine `git-self-update` on production).
6. Retire `FLEET_GIT_ROOT` self-update on production after verification.

## Cooperative upgrade before restart

All channels run the **lifecycle coordinator** first:

1. Fleet sets `draining`, pauses new jobs/proxy work.
2. **`POST …/prepare-stop`** on loopback dependents.
3. Poll **`GET …/stop-readiness`** until `stop_allowed: true` or timeout (**409** `upgrade_blocked`).
4. Git pull, apt signal, or queued root apt apply.
5. Optional **`POST …/resume`** on failure.

See [fleet-lifecycle-contract](../design/fleet-lifecycle-contract.md) and [operate-301/05](../operate-301/05-upgrade-release-and-remote-update.md).

## Timer and signal files

| Channel | Signal path |
|---------|-------------|
| `apt_user` | `~/.local/state/forge-fleet/upgrade-request.json` |
| `apt_system` | `/var/lib/forge-fleet/upgrade-request.json` |

Root **`forge-fleet-apt-upgrade.timer`** runs **`scripts/apt-upgrade-cron.sh`** every minute. Enable via deb postinst or:

```bash
sudo systemctl enable --now forge-fleet-apt-upgrade.timer
land-fleet timer-status
```

Poll **`GET /v1/admin/upgrade/status`** or **`land-fleet upgrade --wait`**.

## Rollback

- Reinstall previous deb version or restore git checkout + `update-user.sh`.
- Dependent lifecycle routes are additive; older Fleet ignores them.
