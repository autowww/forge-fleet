# Fleet Mesh — assumptions and non-goals

## Vocabulary

| Term | Meaning |
|------|---------|
| **Fleet node** | One Fleet daemon + Docker on one host (`fleet.sqlite`, `FLEET_DATA_DIR`) |
| **Peer** | Named remote Fleet in `remote_peers.py` (`etc/remote-peers.json`) |
| **Mesh** | Peers + roles + placement policies; not a distributed SQLite cluster |
| **Cockpit / router** | Laptop Fleet: submit + route; always local |
| **Worker** | Node that executes `docker_argv` jobs |
| **Class A** | Ephemeral batch (`placement_class: ephemeral`); no pinned volumes |
| **Class B** | Stateful compose service with optional replica set |
| **Class C** | Data-primary (single writer + async followers) |
| **Operate loop** | Real-time admission (seconds): can run here *now*? |
| **Plan loop** | Historical optimization (hours+): where *should* it live? |

## Architecture assumption

```
LaptopFleet (cockpit+router)
    |-- placement router at POST /v1/jobs
    |-- peers: lan-nas (tier:lan, role:worker)
    |-- peers: granite (tier:wan, role:worker)
    |
    +-> forward POST /v1/jobs -> chosen worker Fleet -> local Docker
```

LAN preference: probe worker health; on failure fall back to Granite — **do not remove** local Fleet.

## Operator install assumptions

1. **Production operators** install Fleet from signed apt at `https://packages.forgesdlc.com/fleet/ubuntu/` — never `git clone`.
2. **Contributors** continue using `git-install.sh`, `install-update.sh`, and dev venv per Learn 101.
3. **Default laptop role** is cockpit/router with `forge-fleet-user` (port **18766**, user systemd).
4. **Granite and NAS workers** use `forge-fleet` system package (port **18765**) with `--with-docker`.
5. Fleet Python runtime is **stdlib-only** (`pyproject.toml` has no pip deps); debs ship bundled code + trimmed kitchensink CSS.
6. `blueprints/` submodule is **not** required at operator install time.

## Platform tiers

| Tier | Platform | Install | Executes local batch jobs? |
|------|----------|---------|----------------------------|
| 1 | Linux (Ubuntu noble+) | apt `forge-fleet-user` or `forge-fleet` | Yes (when Docker present) |
| 2 | macOS | venv dev path; router-only until launchd | No (Phase 1) |
| 2 | Windows WSL2 | apt inside WSL (same as Linux) | Yes |
| 3 | Windows native | No local Fleet; remote cockpit only | No |

## Granite boundary

All mesh deployment, placement, and data movement use **Fleet HTTP APIs**. Granite SSH is allowed only for Fleet daemon upgrade when `POST /v1/admin/git-self-update` is insufficient — per [granite-operator-boundary.md](../../../design/granite-operator-boundary.md).

## Operator bootstrap from `$HOME`

### Laptop mesh cockpit (user package — default)

Ubuntu 24.04+ (noble):

```bash
curl -fsSL https://packages.forgesdlc.com/fleet/ubuntu/install.sh -o /tmp/forge-fleet-install.sh
bash /tmp/forge-fleet-install.sh --user
```

With Docker dependencies:

```bash
curl -fsSL https://packages.forgesdlc.com/fleet/ubuntu/install.sh -o /tmp/forge-fleet-install.sh
bash /tmp/forge-fleet-install.sh --user --with-docker
```

Convenience one-liner (same behavior; requires GPG-verified apt source inside script — NFR08):

```bash
curl -fsSL https://packages.forgesdlc.com/fleet/ubuntu/install.sh | bash -s -- --user
```

### `install.sh` steps (idempotent)

1. `sudo install -d /usr/share/keyrings`
2. Fetch `gpg.key` → `/usr/share/keyrings/forge-fleet-archive-keyring.gpg`
3. Write `/etc/apt/sources.list.d/forge-fleet.list` with `signed-by=` for noble suite
4. Optional: verify `SHA256SUMS` when `FLEET_VERIFY_CHECKSUMS=1`
5. `sudo apt-get update`
6. `sudo apt-get install -y forge-fleet-user` (+ `forge-fleet-docker` if `--with-docker`)
7. `loginctl enable-linger "$USER"` when `--user`
8. Hint: edit `~/.config/forge-fleet/forge-fleet.env`, `systemctl --user restart forge-fleet.service`
9. Verify: `curl -fsS http://127.0.0.1:18766/v1/health`

### System node (Granite / NAS worker)

```bash
curl -fsSL https://packages.forgesdlc.com/fleet/ubuntu/install.sh -o /tmp/forge-fleet-install.sh
sudo bash /tmp/forge-fleet-install.sh --system --with-docker
```

### Mesh join (after apt install — R11)

```bash
export FORGE_FLEET_BASE_URL="https://<FLEET_PUBLIC_HOSTNAME>"
export FORGE_FLEET_BEARER_TOKEN="<FLEET_BEARER_TOKEN>"

land-fleet join \
  --coordinator "${FORGE_FLEET_BASE_URL}" \
  --enroll-token "${FORGE_FLEET_BEARER_TOKEN}" \
  --label "$(hostname -s)"
```

Or use **`/admin/` → Connect…** wizard (see `docs/learn-101/08-connect-remote-fleet.md`).

### Package layout (R07)

| Package | Installs to | systemd | Port | Data dir |
|---------|-------------|---------|------|----------|
| `forge-fleet` | `/opt/forge-fleet` | system unit | 18765 | `/var/lib/forge-fleet` |
| `forge-fleet-user` | `/usr/lib/forge-fleet/` | user unit | 18766 | `~/.local/state/forge-fleet` |
| `forge-fleet-docker` | — (meta) | — | — | Adds Docker CE apt repo + engine |

### apt lifecycle (operator)

| Intent | Command | Data retained? |
|--------|---------|----------------|
| Install | `apt install forge-fleet-user` | — |
| Update | `apt update && apt upgrade` | Yes (SQLite migrations on start) |
| Stop using | `apt remove forge-fleet-user` | Yes |
| Full uninstall | `apt purge forge-fleet-user` | Config removed; state optional (debconf) |
| Pin version | `apt install forge-fleet-user=0.3.106` | — |

## Maintainer vs operator paths

| Audience | Install path |
|----------|--------------|
| Operator (laptop, Granite, NAS) | apt bootstrap above |
| Contributor | `git clone` + `install-update.sh` / dev venv |
| Installed node update | `apt upgrade` preferred; `git-self-update` only when `FLEET_GIT_ROOT` set (Granite dev) |

## Explicit non-goals

See requirements ledger non-goals table. Additional program-level non-goals:

- Replacing Fleet with Kubernetes or Nomad
- Multi-writer Postgres without controlled failover
- Native Windows/macOS apt packages in Phase 1
- Drag-drop placement UI before propose/apply API exists
- Implicit resource inference from `docker_argv` without `meta.resources` (Phase 2+)
