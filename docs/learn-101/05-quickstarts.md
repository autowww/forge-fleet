# Forge Fleet quickstarts

**Audience:** Developers picking a track, or operators sanity-checking an install. **Outcome:** Run the **Verify** block for your path (local, bare metal, workspace, templates, TLS). **Prerequisites:** Shell and **`curl`**; Docker for job-related sections.

Each section ends with **Verify** steps you can run from the same shell (adjust host/port).

Default ports: **18765** (CLI default), **18766** (common user install). Replace **`$BASE`** and **`$TOKEN`** below.

```bash
export BASE=http://127.0.0.1:18765
curl_auth=( )
[[ -n "${FLEET_TOKEN:-}" ]] && curl_auth=( -H "Authorization: Bearer ${FLEET_TOKEN}" )
```

## 1. Local developer (5–10 min)

1. Prefer the guided **[Install & run locally](02-install-run-local-dev.md)** page (venv + Compose recap); then **`pip install -e .`** via **[Git install](04-git-install.md)** if you need packaging detail.
2. Run **`fleet-server --host 127.0.0.1 --port 18765`** with a writable **`FLEET_DATA_DIR`**, or use your install’s **`systemctl --user`** unit.
3. Open **`/admin/`** if the bind is loopback.

**Verify**

```bash
curl -sS "${BASE}/v1/version" | head -c 400; echo
curl -sS "${curl_auth[@]}" "${BASE}/v1/health" | head -c 400; echo
```

Expect **200** and JSON. If you set **`FLEET_BEARER_TOKEN`** and bind beyond loopback, include **`Authorization`**.

## 2. Fresh host operator (20–45 min)

1. Follow [HOST-BOOTSTRAP.md](03-host-bootstrap.md) for Docker/OS and (optional) Caddy.
2. Install Fleet per [GIT-INSTALL.md](04-git-install.md); set **`FLEET_BEARER_TOKEN`** in **`forge-fleet.env`** for non-loopback binds.
3. **`systemctl --user enable --now forge-fleet.service`** (or your distro equivalent).

**Verify**

```bash
curl -sS "${curl_auth[@]}" "${BASE}/v1/version"
curl -sS "${curl_auth[@]}" "${BASE}/v1/health"
curl -sS "${curl_auth[@]}" "${BASE}/v1/admin/snapshot" | head -c 600; echo
```

Expect **200** for all three. **`/v1/admin/snapshot`** is large—pipe to **`head`** or **`jq`** filters.

## 3. First API job (after server is up)

Requires Docker available to the Fleet process. See [EXAMPLES.md](../build-201/05-examples-and-recipes.md) for a full **`docker run`** example.

**Verify**

```bash
# After POST /v1/jobs returns {"id":"..."}:
curl -sS "${curl_auth[@]}" "${BASE}/v1/jobs/<job_id>"
```

Expect **`status`** to move from **`queued`** → **`running`** → terminal state.

## 4. Workspace upload job (longer)

1. **`POST /v1/jobs`** with **`meta.workspace_upload_required`: true** and optional manifest flags — [WORKSPACE_UPLOAD.md](../build-201/01-workspace-upload.md).
2. **`PUT /v1/jobs/{id}/workspace`** with gzip tarball.
3. Poll **`GET /v1/jobs/{id}`**.

**Verify:** job **`meta.workspace_state`** progresses to **`ready`**; then runner starts the container.

## 5. Container template build (Docker host)

1. Ensure **`requirement_templates.json`** and Docker/BuildKit per [CONTAINER-TEMPLATES.md](../build-201/02-container-templates.md).
2. **`POST /v1/container-templates/build`** with requirement ids.

**Verify**

```bash
curl -sS "${curl_auth[@]}" "${BASE}/v1/container-templates/status"
```

## 6. Caddy / TLS front (20–60 min)

Follow [CADDY-SYSTEMD.md](../build-201/03-caddy-systemd.md) or [CADDY-UNIFIED-GRANITE.md](../build-201/04-caddy-unified-granite.md). DNS + certificates dominate wall time.

**Verify:** **`curl https://your-host/v1/health`** with correct **`Authorization`** when bearer is required.

## 7. Remote git self-update (maintainer)

From a machine that can reach the API: **`POST /v1/admin/git-self-update`** with bearer — see [API-REFERENCE.md](../reference/01-http-api-reference.md) and [README.md](../../README.md). System installs under **`/opt/forge-fleet`** may return **400** with a host-shell command instead.

**Verify:** **`GET /v1/version`** shows updated **`package_semver`** / git metadata after restart.

## Common failures

| Symptom | What to do |
|---------|------------|
| **401** on **`/v1/*`** | Send **`Authorization: Bearer`** when a token is configured or the bind is not loopback-only. |
| **`docker: not found`** or jobs stuck **queued** | Install Docker/Podman; see **[Host bootstrap](03-host-bootstrap.md)**. |
| Workspace job never leaves **pending_upload** | **`PUT /v1/jobs/{id}/workspace`** with a valid gzip tar; see **[Workspace upload](../build-201/01-workspace-upload.md)**. |
| **502** via Caddy | Confirm Fleet listens where the proxy expects; **`curl`** Fleet loopback. |

**More:** **[Troubleshooting](../operate-301/04-troubleshooting.md)**.
