# Granite — Open WebUI + web ChatGPT/Gemini accounts

Operator runbook for Fleet-managed Open WebUI on Granite with signed-in **web** accounts (not API keys only).

## Boundary

- Deploy via Fleet HTTP and [deploy/open-webui](../../deploy/open-webui/README.md). No SSH `docker compose`.
- Laptop `~/.config/microsoft-edge` is never copied. Market harvest profile stays on CDP `:9222`.
- UI uses **hostname B**, not `/v1/app-gateways/`. On `forgedc.net`, public URL is **`https://webui.forgedc.net`** via the **Granite Cloudflare tunnel** to loopback `:19808` (same connector as `granite.forgedc.net`). Caddy `OPEN_WEBUI_SITE_ADDRESS` is optional for direct host TLS; tunnel is the normal laptop path.
- Bootstrap DNS + ingress: `deploy/open-webui/scripts/apply-cf-webui-tunnel.sh` (uses `CF_TUNNEL_ID=07ff2cbc-4741-4737-a0e5-10a60a884efd` on Granite). Set `WEBUI_URL=https://webui.forgedc.net` in deploy `.env`.

## Sequence

1. Roll out compose (`scripts/rollout-open-webui.sh` or container-services API).
2. Apply Cloudflare tunnel + DNS (`apply-cf-webui-tunnel.sh`), or refresh unified Caddy with `OPEN_WEBUI_SITE_ADDRESS` when not using tunnel.
3. Install account-plane units (`install-open-webui-account-plane.sh`). Default **`FORGE_OPEN_WEBUI_HEADLESS=1`**: **Chromium** (Google Chrome on Granite) runs `--headless=new` (no Granite GUI / no `DISPLAY=:0`).
4. **Sign-in without Granite GUI:** Granite runs headless Chromium. Preferred: the Fleet CDP stream sign-in used by the Market edge plane (`granite-market-edge-plane.md`), targeting the account's CDP port (`:9230` chatgpt, `:9231` gemini). **Bootstrap only — operator-granted SSH:** `deploy/open-webui/scripts/granite-open-webui-auth-laptop.sh chatgpt-primary` opens an SSH tunnel `:19230`/`:19231` → Granite and a Playwright Inspector on the laptop for OAuth; run it only when the operator explicitly grants SSH in that message (see `granite-no-ssh-without-permission.mdc`). Alternative without SSH: pack profile (`pack-open-webui-edge-profile.sh` + Fleet upload). Use dedicated `~/.config/chromium-granite-*` dirs — not operator Edge/Market profiles.
5. Register bridge URLs in Open WebUI admin (see deploy README §4). The bridge bearer per account is in `~/.config/forge-open-webui/bridge-<slug>.env` on Granite (created 0600 by the installer; required by default — `FORGE_WEB_BRIDGE_REQUIRE_BEARER=1`).

## Bridge limits (per account process)

| Env | Default | Effect |
|---|---|---|
| `FORGE_WEB_BRIDGE_REQUIRE_BEARER` | `1` | `503 bearer_not_configured` until a bearer is set; `0` only for loopback dev |
| `FORGE_WEB_BRIDGE_MAX_QUEUE` | `4` | one prompt in flight per signed-in tab; more than this many waiting → `429` + `Retry-After: 5` |
| `FORGE_WEB_BRIDGE_TIMEOUT_S` | `180` | wall-clock bound per provider call → `504` |
| `x-forge-request-id` | minted | echoed on every response (header and `chatcmpl-<id>`); pass your own for tracing |

`GET /health` reports `bearer_configured`, `inflight`, `waiting`, `max_queue`, `timeout_s`. `stream: true` returns one SSE delta with the full answer (web sessions do not stream tokens).

## Consumer API (Open WebUI keys)

`.env` sets `ENABLE_API_KEYS=true`, `ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS=true`, `API_KEYS_ALLOWED_ENDPOINTS=/api/chat/completions,/api/models`. Each user mints a key in **Settings → Account → API keys**; apps on the laptop or Granite call:

```bash
curl -fsS https://webui.forgedc.net/api/models -H "Authorization: Bearer $OPEN_WEBUI_API_KEY"
curl -fsS https://webui.forgedc.net/api/chat/completions \
  -H "Authorization: Bearer $OPEN_WEBUI_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"granite-chatgpt-primary","messages":[{"role":"user","content":"Say hi"}]}'
```

Model ids: `granite-chatgpt-primary`, `granite-chatgpt-primary.gpt-4o`, `granite-gemini-primary`, … (bridge `/v1/models`). Agents in Cursor use the LCDL MCP tool `lcdl.web_chat` instead (forge-lcdl `docs/mcp-sidecar.md`).

## Fleet capability follow-up

The production sign-in path must not need SSH. Open item: extend the Market edge-plane CDP stream (`forge_fleet` edge routes) to the Open WebUI account ports `:9230`/`:9231` so the operator completes OAuth/Turnstile from the laptop browser through Fleet. Until then `granite-open-webui-auth-laptop.sh` stays bootstrap-only and refuses to run without `FORGE_OPERATOR_GRANTED_SSH=1`.

## References

- [Granite operator boundary](../design/granite-operator-boundary.md)
- [Granite Market edge plane](granite-market-edge-plane.md) (CDP stream sign-in pattern)
- [Unified Caddy](../build-201/04-caddy-unified-granite.md)
