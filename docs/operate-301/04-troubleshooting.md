# Troubleshooting

Symptom-first pointers. Always check **`journalctl`** for the Fleet unit and confirm **`curl`** targets the same host/port your clients use.

## **401** or **403** on `/v1/*`

| Likely cause | What to do |
|--------------|------------|
| Missing bearer on non-loopback | Set **`Authorization: Bearer $FLEET_BEARER_TOKEN`**. |
| Wrong token | Rotate token in env + clients. |
| **`FLEET_ENFORCE_BEARER`** on loopback | Send bearer even locally. |
| Workspace-worker route | Use **`X-Workspace-Worker-Token`**, not bearer. |

## **`GET /admin/`** blank or unstyled

Hard-refresh the browser. Confirm Fleet version matches a release that includes **`/admin/ks/`** assets. Check network tab for **404** on CSS/JS.

## **`docker: not found`** or jobs stuck **queued**

Install Docker or Podman per [HOST-BOOTSTRAP.md](../learn-101/03-host-bootstrap.md). Set **`FLEET_DOCKER_BIN`** if the binary is non-standard.

## Podman vs Docker confusion

Fleet shells out to whatever **`docker`** resolves to; some hosts symlink Podman. If behavior differs from pure Docker, diagnose with **`docker version`** and image pull policies.

## Template **`build`** failure

See [CONTAINER-TEMPLATES.md](../build-201/02-container-templates.md): BuildKit, requirement ids, Dockerfile paths. Inspect **`GET /v1/container-templates/status`** errors and Docker build logs on the host.

## Workspace **`extract_failed`**

Tar must be **gzip**; paths must not escape extraction root; optional manifest digests must match. See [WORKSPACE_UPLOAD.md](../build-201/01-workspace-upload.md).

## **502** through Caddy, **200** direct to Fleet

Upstream mismatch—Caddy cannot reach Fleet listen address, wrong port in `reverse_proxy`, or TLS backend misconfig. **`curl` loopback to Fleet** bypasses Caddy for isolation.

## **`git-self-update`** returns **400** with **`system_root_install_command`**

Expected on **`/opt`** installs—run the printed host command with **`sudo`** from the git checkout; see [README.md](../../README.md).

## Still stuck

Collect: **`/v1/version`** JSON, **`/v1/health`**, last **200** lines of **`journalctl`**, and whether bind is loopback or LAN.
