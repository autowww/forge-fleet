# One hostname for Fleet + Ollama (public edge)

If a single public URL (HTTPS) must serve **both**:

- **Forge Fleet** — `GET /v1/health`, `GET /v1/version`, jobs API, `/admin/`, …
- **Ollama** (OpenAI-style) — `GET /v1/models`, `POST /v1/chat/completions`, `GET /api/tags`, …

then **every path must be routed by URL**, not by sending all traffic to Ollama alone.

Use placeholders in runbooks — store live values in env or secrets files only:

| Placeholder | Typical env |
|-------------|-------------|
| `<FLEET_PUBLIC_BASE_URL>` | `FORGE_FLEET_BASE_URL` |
| `<FLEET_PUBLIC_HOSTNAME>` | `CADDY_SITE_ADDRESS` (hostname only) |
| `<FLEET_BEARER_TOKEN>` | `FLEET_BEARER_TOKEN` / `FORGE_FLEET_BEARER_TOKEN` |
| `<LLM_BEARER_TOKEN>` | `LLM_BEARER_TOKEN` |

## Symptom when misconfigured

- `curl -sS -o /dev/null -w '%{http_code}\n' -H 'Authorization: Bearer <LLM_BEARER_TOKEN>' https://<FLEET_PUBLIC_HOSTNAME>/v1/models` → **200**
- `curl -sS -o /dev/null -w '%{http_code}\n' -H 'Authorization: Bearer <FLEET_BEARER_TOKEN>' https://<FLEET_PUBLIC_HOSTNAME>/v1/health` → **401** with body `Unauthorized`

That pattern usually means **`/v1/health` is still hitting Ollama** (or another service that enforces the LLM gate only). Ollama does not implement Fleet’s health JSON; it rejects unknown bearer tokens on many paths.

**Fingerprint (unified installer LLM gate):** if `curl -sSI -H 'Authorization: Bearer <FLEET_BEARER_TOKEN>' https://<FLEET_PUBLIC_HOSTNAME>/v1/health` shows `content-type: text/plain` and body length **12** (`Unauthorized`), the request reached the **Ollama `handle` with `LLM_BEARER_TOKEN` checks**, not Forge Fleet (Fleet API 401s are **`application/json`** with `{"ok":false,"error":"unauthorized"}`). Fix routing on the **origin** behind Cloudflare, not the token string in certificator alone.

Cross-check: same host with the **LLM** bearer on `/v1/health` often returns **404** from Ollama; with the **Fleet** bearer, **401** `Unauthorized` plain text — same mis-route.

## Fix

1. Run the **unified** installer from the forge-fleet repo (same machine that runs Fleet and Ollama, or one that can reverse-proxy to both):

   ```bash
   cd /path/to/forge-fleet
   LAYOUT=user \
   FLEET_BEARER_TOKEN='<FLEET_BEARER_TOKEN>' \
   LLM_BEARER_TOKEN='<LLM_BEARER_TOKEN>' \
   bash ./scripts/install-caddy-fleet-ollama-unified.sh --non-interactive
   ```

2. For **TLS on a real hostname** (instead of `http://0.0.0.0:18767`), set **`CADDY_SITE_ADDRESS`** to the public name so the generated site block uses automatic HTTPS (requires DNS pointing at this host and ports 80/443 reachable for ACME, unless you use your own TLS elsewhere):

   **Non-interactive** (env vars are applied exactly; no prompts):

   ```bash
   CADDY_SITE_ADDRESS=<FLEET_PUBLIC_HOSTNAME> \
   LAYOUT=user \
   FLEET_BEARER_TOKEN='<FLEET_BEARER_TOKEN>' \
   LLM_BEARER_TOKEN='<LLM_BEARER_TOKEN>' \
   bash ./scripts/install-caddy-fleet-ollama-unified.sh --non-interactive
   ```

   **Interactive:** after the port questions, answer the **“CADDY_SITE_ADDRESS (TLS hostname, or empty):”** prompt with `<FLEET_PUBLIC_HOSTNAME>`, or rely on a line already saved in **`~/.config/forge-fleet/forge-fleet.env`** (`CADDY_SITE_ADDRESS=…`). Passing `CADDY_SITE_ADDRESS=…` on the command line without `--non-interactive` also works if the value is still set when the prompt runs (defaults are pre-filled).

   For HTTPS on a non-standard port:

   ```bash
   CADDY_SITE_ADDRESS='<FLEET_PUBLIC_HOSTNAME>:8443'
   ```

3. If the public site is served by **stock** `caddy.service` and a different file (e.g. `/etc/caddy/Caddyfile`), **merge** the same routing into that file, or replace it with the output of this installer. A config that only `reverse_proxy`s to `127.0.0.1:11434` will never satisfy Fleet health checks.

4. **Cloudflare Tunnel** to a local port (for example `http://127.0.0.1:18767`) only forwards bytes; **unified Caddy on that port** must still route `/v1/health` to Fleet before the LLM bearer gate. After changing the Caddyfile, run **`systemctl --user restart forge-fleet-caddy.service`** (user layout) or restart the system Caddy unit. Point the tunnel **Public Hostname** at that loopback URL in the Cloudflare Zero Trust dashboard — Fleet does not create tunnels via API.

5. **Bearer alignment:** the token inlined in the Caddyfile for Fleet `header_up Authorization` must match **`FLEET_BEARER_TOKEN`** on the **forge-fleet** process (`~/.config/forge-fleet/forge-fleet.env` or your unit). If they differ, `/v1/health` can return **401** with **`application/json`** from Fleet (certificator still reports it as a Fleet bearer problem).

## Routing order (generated)

1. **`handle /v1/health*`**, **`handle /v1/version*`** → Fleet upstream (bearer injected when `FLEET_BEARER_TOKEN` is set in the installer).
2. **Ollama paths** — `/v1/chat/completions*`, `/v1/completions*`, `/v1/models*`, `/v1/embeddings*`, `/api/*` — optional `LLM_BEARER_TOKEN` check at the edge; `Authorization` stripped before proxy to Ollama.
3. **`handle /admin*`** (when `FLEET_CADDY_ADMIN_LOOPBACK_ONLY=1`, default) — **403** for non-loopback `remote_ip`; localhost/SSH tunnel only; bearer injected upstream.
4. **`handle /v1/admin/*`** (when `FLEET_CADDY_ADMIN_API_CLIENT_BEARER=1`, default) — Fleet upstream **without** bearer injection; client must send `Authorization: Bearer`.
5. **Catch-all** → Fleet (`/v1/jobs`, app-gateways, …) with bearer injection unchanged for workers and certificator.

Disable admin hardening: `FLEET_CADDY_ADMIN_LOOPBACK_ONLY=0` and/or `FLEET_CADDY_ADMIN_API_CLIENT_BEARER=0` before re-running the unified installer.

## Admin lock verification (public host)

```bash
BASE=<FLEET_PUBLIC_BASE_URL>
curl -sS -o /dev/null -w 'admin HTML=%{http_code}\n' "$BASE/admin/"
curl -sS -o /dev/null -w 'admin snapshot no auth=%{http_code}\n' "$BASE/v1/admin/snapshot"
curl -sS -o /dev/null -w 'admin snapshot with bearer=%{http_code}\n' \
  -H "Authorization: Bearer $FORGE_FLEET_BEARER_TOKEN" "$BASE/v1/admin/snapshot"
```

Expect **403** / **401** / **200** respectively after deploy. View the remote host from a laptop via local Fleet **`/admin/` → Connect…** or **Remote scope** (`PUT /v1/remote-peers/<id>` with base URL + bearer).

## Quick verification (after deploy)

Replace `BASE`, tokens, and paths to match your host.

```bash
BASE=<FLEET_PUBLIC_BASE_URL>
curl -sS -o /dev/null -w 'LLM models=%{http_code}\n' -H "Authorization: Bearer <LLM_BEARER_TOKEN>" "$BASE/v1/models"
curl -sS -o /dev/null -w 'Fleet health=%{http_code}\n' -H "Authorization: Bearer <FLEET_BEARER_TOKEN>" "$BASE/v1/health"
```

Expected when Caddy injects Fleet bearer upstream: Fleet health may return **200** even if the client sends no `Authorization` header, depending on your Fleet settings; if you require a client bearer at the edge, keep `FORGE_FLEET_BEARER_TOKEN` in certificators aligned with **`FLEET_BEARER_TOKEN`** on the Fleet host.

## Related

- `03-caddy-systemd.md` — user vs system layout, linger, logs.
- `scripts/install-caddy-fleet-ollama-unified.sh` — generator and env vars (`CADDY_SITE_ADDRESS`, `LLM_BEARER_TOKEN`, …).
- `scripts/update-fleet-unified-caddy.sh` — `git pull` then non-interactive unified install.
- **[Learn 101 — Connect to remote Fleet](../learn-101/08-connect-remote-fleet.md)** — laptop operator path.
