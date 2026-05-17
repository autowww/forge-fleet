# Security

Forge Fleet is an **operator-controlled orchestrator**. It can run **arbitrary container images**, read/write **`FLEET_DATA_DIR`**, and (when configured) mutate git checkouts for self-update. Treat bearer tokens and host access accordingly.

## Threat model (high level)

| Risk | What breaks | Mitigation |
| --- | --- | --- |
| **Bearer / token leak** | Remote job submission, snapshot exfil | Short TTL secrets, rotation, **no** tokens in CI logs; use **mTLS** or **IP allow lists** where practical |
| **Docker socket / daemon** | Host compromise via privileged workloads | Restrict who gets API tokens; use **rootless** / **gVisor** / VM boundaries per org policy |
| **Host filesystem via data dir** | SQLite + template trees tampered | File permissions on **`FLEET_DATA_DIR`**; separate disk for prod |
| **Workspace archive traversal / symlink** | Unexpected writes on extract | Keep Fleet patched; avoid untrusted job creators (**[Workspace upload](../build-201/01-workspace-upload.md)**) |
| **Template image trust** | Supply-chain pull/build of malicious layers | Vet Dockerfiles; pin digests where possible (**[Templates](../build-201/02-container-templates.md)**) |
| **Managed services exposure** | Long-lived compose stacks on same host | Network policy + firewall; least privilege |
| **Logs / backups** | Secrets in tarball or DB dumps | Encrypt backups; redact **`Authorization`** headers in proxies |
| **`/admin/` exposure** | Browser-accessible job metadata | Bind to loopback or protect with **Caddy** **basic_auth**/network ACLs |

**Trust boundary (prose):** callers on the **trusted** side of your API perimeter may cause **Fleet** to invoke **Docker** on **this host**. Anyone who can enqueue **`docker_argv`** jobs should be cleared to run arbitrary containers *subject to your Docker policy*—that is **not** a multi-tenant safe boundary by default.

```blueprint-diagram-ascii
key: network
alt: High-level trust zones around Fleet
caption: External callers cross TLS to Caddy; Fleet controls Docker on the host.
Clients -> TLS -> Caddy -> Fleet loopback -> Docker socket -> Containers
```

## Authentication

- **`FLEET_BEARER_TOKEN`** protects **`/v1/*`** JSON when the server listens beyond loopback (unless **no token** is configured — development only). **`FLEET_ENFORCE_BEARER`** forces bearer checks even on loopback.
- **Admin HTML** (`/admin/`) is served **without** bearer by design; still only safe when network access to the bind address is trusted.
- **Workspace-worker** endpoints use **`X-Workspace-Worker-Token`**, not the admin bearer.

## Reverse proxy and TLS

Typical production setups terminate HTTPS at **Caddy** or another proxy and forward HTTP to Fleet. Ensure **network ACLs** restrict who can hit Fleet’s port; TLS on the public name is handled by the proxy, not Fleet itself.

## Docker socket and workload power

Fleet runs **`docker`** (or **`podman`**) commands on behalf of callers. Anyone who can **`POST /v1/jobs`** with an effective token can schedule workloads—**treat API tokens as root-equivalent on that host** for many practical purposes.

## Token injection into jobs

When **`FLEET_INJECT_HOST_METRICS_ENV_IN_DOCKER`** is enabled, the **Fleet bearer** may be copied into container environments for **`GET /v1/health`** access. Malicious workloads or log pipelines can exfiltrate it—keep this flag off unless you accept the risk.

## Workspace uploads

Tarballs are extracted under **`FLEET_DATA_DIR`** with path guards (**`workspace_bundle.py`**). Manifests (**`.forge_workspace_manifest.json`**) add digest checks. Residual risk remains for logical bugs—verify Fleet versions and avoid running untrusted job creators.

## Template package upload

**`PUT .../container-templates/{id}/package`** writes into **`etc/containers`** trees and can trigger **docker build** with network access depending on Dockerfiles. Restrict callers and vet packages.

## Self-update

**`git pull` plus install scripts** can change the running service and scripts on disk. Protect **`FLEET_GIT_ROOT`** permissions and bearer tokens; system installs may intentionally refuse button-style updates and require host-shell **`sudo`**.

## Logging

Do not paste bearer tokens or workspace-worker tokens into public logs or screenshots.

## See also

- **[Configuration & environment](../reference/03-configuration-and-env.md)** — environment knobs  
- **[HTTP API reference](../reference/01-http-api-reference.md)** — auth matrix
