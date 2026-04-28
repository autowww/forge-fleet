# One hostname for Fleet + Ollama (e.g. granite.forgedc.net)

If a single public URL (HTTPS) must serve **both**:

- **Forge Fleet** — `GET /v1/health`, `GET /v1/version`, jobs API, `/admin/`, …
- **Ollama** (OpenAI-style) — `GET /v1/models`, `POST /v1/chat/completions`, `GET /api/tags`, …

then **every path must be routed by URL**, not by sending all traffic to Ollama alone.

## Symptom when misconfigured

- `curl -sS -o /dev/null -w '%{http_code}\n' -H 'Authorization: Bearer <LLM_TOKEN>' https://example/v1/models` → **200**
- `curl -sS -o /dev/null -w '%{http_code}\n' -H 'Authorization: Bearer <FLEET_TOKEN>' https://example/v1/health` → **401** with body `Unauthorized`

That pattern usually means **`/v1/health` is still hitting Ollama** (or another service that enforces the LLM gate only). Ollama does not implement Fleet’s health JSON; it rejects unknown bearer tokens on many paths.

## Fix

1. Run the **unified** installer from the forge-fleet repo (same machine that runs Fleet and Ollama, or one that can reverse-proxy to both):

   ```bash
   cd /path/to/forge-fleet
   LAYOUT=user \
   FLEET_BEARER_TOKEN='…same as fleet FLEET_BEARER_TOKEN…' \
   LLM_BEARER_TOKEN='…DellPrecisionLLM or other LLM edge secret…' \
   bash ./scripts/install-caddy-fleet-ollama-unified.sh --non-interactive
   ```

2. For **TLS on a real hostname** (instead of `http://0.0.0.0:18767`), set **`CADDY_SITE_ADDRESS`** to the public name so the generated site block uses automatic HTTPS (requires DNS pointing at this host and ports 80/443 reachable for ACME, unless you use your own TLS elsewhere):

   ```bash
   CADDY_SITE_ADDRESS=granite.forgedc.net \
   LAYOUT=user \
   FLEET_BEARER_TOKEN='…' \
   LLM_BEARER_TOKEN='…' \
   bash ./scripts/install-caddy-fleet-ollama-unified.sh --non-interactive
   ```

   For HTTPS on a non-standard port:

   ```bash
   CADDY_SITE_ADDRESS='granite.forgedc.net:8443'
   ```

3. If the public site is served by **stock** `caddy.service` and a different file (e.g. `/etc/caddy/Caddyfile`), **merge** the same routing into that file, or replace it with the output of this installer. A config that only `reverse_proxy`s to `127.0.0.1:11434` will never satisfy Fleet health checks.

## Routing order (generated)

1. **`/v1/health`**, **`/v1/version`** → Fleet upstream (bearer injected when `FLEET_BEARER_TOKEN` is set in the installer).
2. **Ollama paths** — `/v1/chat/completions*`, `/v1/completions*`, `/v1/models*`, `/v1/embeddings*`, `/api/*` — optional `LLM_BEARER_TOKEN` check at the edge; `Authorization` stripped before proxy to Ollama.
3. **Everything else** → Fleet (same injection rules as step 1).

## Quick verification (after deploy)

Replace `BASE`, tokens, and paths to match your host.

```bash
BASE=https://granite.forgedc.net
curl -sS -o /dev/null -w 'LLM models=%{http_code}\n' -H "Authorization: Bearer DellPrecisionLLM" "$BASE/v1/models"
curl -sS -o /dev/null -w 'Fleet health=%{http_code}\n' -H "Authorization: Bearer DellPrecisionFleet" "$BASE/v1/health"
```

Expected when Caddy injects Fleet bearer upstream: Fleet health may return **200** even if the client sends no `Authorization` header, depending on your Fleet settings; if you require a client bearer at the edge, keep `FORGE_FLEET_BEARER_TOKEN` in certificators aligned with **`FLEET_BEARER_TOKEN`** on the Fleet host.

## Related

- `docs/CADDY-SYSTEMD.md` — user vs system layout, linger, logs.
- `scripts/install-caddy-fleet-ollama-unified.sh` — generator and env vars (`CADDY_SITE_ADDRESS`, `LLM_BEARER_TOKEN`, …).
- `scripts/update-fleet-unified-caddy.sh` — `git pull` then non-interactive unified install.
