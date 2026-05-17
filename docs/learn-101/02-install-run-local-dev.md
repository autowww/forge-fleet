# Learn 101 — Install and run locally (developer loop)

**Outcome:** Fleet answers **`GET /v1/health`** on your workstation with Docker available for **`docker_argv`** jobs.

**Audience:** developers on macOS/Linux. **Time:** ~20–40 minutes. **Verify:** **`curl http://127.0.0.1:18765/v1/version`** returns JSON while the server runs.

## Prerequisites

| Requirement | Notes |
|-------------|------|
| **Python ≥ 3.11** | Matches **`pyproject.toml`** runtime |
| **Docker Engine** | Daemon reachable by your user (`docker info`) |
| **git** | Clone + submodule workflows |

Stronger OS/package guidance for bare metal lives in **[Host bootstrap](03-host-bootstrap.md)** (run that before **`git-install.sh`** on servers).

## Path A — editable install + CLI server

```bash
git clone <YOUR_FORGE_FLEET_REPO_URL> forge-fleet
cd forge-fleet
git submodule update --init --recursive
python3 -m venv .venv
.venv/bin/pip install -e .
export FLEET_BEARER_TOKEN='dev-token'    # optional on loopback-only binds
.venv/bin/python -m fleet_server --host 127.0.0.1 --port 18765
```

**Auth recap**

| Listen address | **`FLEET_BEARER_TOKEN` unset** | With token |
|----------------|-----------------------------------|------------|
| **`127.0.0.1` only** | Often **no** bearer required | Bearer honored if sent |
| **`0.0.0.0`** / LAN | Usually **requires** bearer | Match **`Authorization`** everywhere |

See **[Security](../operate-301/01-security.md)** before exposing Fleet beyond localhost.

## Path B — Docker Compose

From repo root:

```bash
docker compose up --build
```

Compose binds **`18765`** by default and persists **`FLEET_DATA_DIR`** via the named volume—**Recent jobs** survive container restarts.

## Defaults worth memorizing

| Topic | Typical value |
|-------|----------------|
| **Port** | **18765** (CLI default) vs **18766** (**`install-user.sh`**) |
| **Data dir** | **`FLEET_DATA_DIR`** (SQLite + **`etc/`** overlays) |

## Verify

```bash
export BASE=http://127.0.0.1:18765
curl_auth=( )
[[ -n "${FLEET_BEARER_TOKEN:-}" ]] && curl_auth=( -H "Authorization: Bearer ${FLEET_BEARER_TOKEN}" )

curl -sS "${BASE}/v1/version" | head -c 400; echo
curl -sS "${curl_auth[@]}" "${BASE}/v1/health" | head -c 400; echo
```

Expect **HTTP 200** and JSON bodies.

## Common failures

| Symptom | Likely fix |
|---------|------------|
| **`docker: not found`** | Install/start Docker; PATH includes **`docker`** |
| **`401`/`403` on `/v1/*`** | Send bearer when listening beyond loopback |
| **`Address already in use`** | Another Fleet instance owns the port—pick another **`--port`** |
| Admin blank styling | Hard refresh; confirm **`/admin/ks/`** assets load (**see Troubleshooting**) |

## Troubleshooting mini-ladder

1. Confirm **`curl`** targets the **same host/port** Studio uses.
2. Read **`journalctl --user -u forge-fleet.service`** (user layout) or **`journalctl -u forge-fleet.service`** (system layout).
3. Escalate to **[Operate 301 troubleshooting](../operate-301/04-troubleshooting.md)**.

## Next steps

| Step | Doc |
|------|-----|
| Ship-ready host timeline | **[Host bootstrap](03-host-bootstrap.md)** · **[Git install](04-git-install.md)** |
| Scripted verification bundles | **[Quickstarts](05-quickstarts.md)** |
| First **`docker_argv` job walk-through | **[Your first Fleet job](06-first-fleet-job.md)** |
