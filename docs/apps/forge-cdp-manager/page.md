# Forge CDP Manager

Install this **Fleet App** to inspect and reclaim **CDP surface leases**, toggle the session manager, and monitor **forge-cdp-serve** sessions from Fleet `/admin/`.

## Changelog

### 0.3.0

- **Control clarity** — session manager vs managed/external/off daemon process vs HTTP reachable; reconcile alerts when env disagrees with Fleet config.
- **Surface overview** and **registered workers** tables from `GET /v1/fleet` per Edge CDP port.
- **Session telemetry** — heartbeat, progress message, counts, CDP URL, sync run id; per-row and bulk cancel actions.
- **Scoped stale release** for Cockpit `:9222` and KA `:9223`.
- Stream preview page **Cancel session** button (requires Fleet host with FAEP action routing).

### 0.2.0

- Manifest version stamped from `pyproject.toml` at build time.
- Fleet tab: manager/daemon toggles, live sessions table, session event feed, stream preview links.
- **Prepare Edge sessions** — attach to operator CDP or launch isolated KA profile on :9223.
- Runtime config at `{FLEET_DATA_DIR}/etc/fleet-apps-runtime/forge-cdp-manager.json`.
- Requires `invoke_local_cli` permission to start/stop a local `forge-cdp-serve` subprocess.

## What you get

- A **CDP Manager** tab in Fleet `/admin/` with live lease table and stale reclaim action.
- **In-package docs** mirrored at `/admin/apps/forge-cdp-manager/docs/` on your Fleet host.

## Trust boundary

- Handlers read lease files under `~/.cache/forge-cdp/leases` (or `FORGE_CDP_MANAGER_LOCK_DIR`).
- Fleet does not attach Playwright from this tab; **Prepare Edge sessions** can launch an isolated Edge profile for KA or guide operator debugging for Cockpit.
- This package does not replace Cockpit HTTP routes on port 9775.

## Prerequisites

- Fleet with FAEP v1 (`POST /v1/fleet-apps/install`).
- `pip install` target includes `forge-cdp-manager` wheel from the package zip.

## Install from Fleet admin

1. Open **`/admin/`** → **Apps** tab.
2. Click **Install** next to **Forge CDP Manager**.
3. Open the **Forge CDP Manager** tab to view leases.

## HTTP control plane (:18770)

When `forge-cdp-serve` runs on the operator machine:

- Fleet lease tab reads flock files (same as today).
- Operators and agents can also use `GET /v1/fleet` and `GET /v1/leases` on `http://127.0.0.1:18770`.
- Set `FORGE_CDP_MANAGER_URL` on Cockpit and Knowledge Assistant consumers.

See [CDP-OPERATOR-RUNBOOK.md](https://github.com/autowww/forge-cdp-manager/blob/main/docs/CDP-OPERATOR-RUNBOOK.md) in the upstream repo.

## See also

- Upstream repo: [forge-cdp-manager](https://github.com/autowww/forge-cdp-manager)
- Protocol: [Fleet Apps](../build-201/03-fleet-apps-protocol.md)
