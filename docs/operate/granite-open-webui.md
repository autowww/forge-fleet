# Mercury — Open WebUI

Operator runbook for Open WebUI on **Mercury**. Browsers sign in with Google through **`https://login.forgedc.net`**. Forge jobs keep using per-user Open WebUI API keys. ChatGPT, Gemini, and the Forge LLM gateway stay on **Granite**.

## Boundary

- Public UI: **`https://webui.forgedc.net`**. Mercury Cloudflare tunnel `6e783b10-a38e-4715-a57e-f55c649fcba2` sends that hostname to the auth gate on `127.0.0.1:19809`, which proxies to Open WebUI on `127.0.0.1:19808`.
- A browser with no cookie is redirected to `https://login.forgedc.net/api/auth/oidc/start?return_to=https://webui.forgedc.net`. After Google accepts an **active** Lenses tenant, the gate sets a host cookie and sends `X-Forwarded-Email` to Open WebUI. `Authorization: Bearer` (API keys) is passed through and does not require Google.
- Deploy compose with [deploy/open-webui](../../deploy/open-webui/README.md) on Mercury (`open-webui-host-guard.sh` allows Mercury). Ingress and DNS: `deploy/open-webui/scripts/apply-cf-webui-tunnel.sh` (Mercury tunnel, origin `:19809`).
- **Not on the operator ASUS laptop:** do not run Open WebUI compose locally; use **`deploy/open-webui/scripts/stop-open-webui-local.sh`** if containers appear.
- Granite `forge-open-webui` and `forge-open-webui-postgres` stay stopped. Their Docker volumes remain the rollback copy. Do not publish the Granite gateway (`:18080`) or web bridges (`:9240`, `:9241`) as public hostnames. Mercury reaches them only through the user service `forge-openwebui-granite-forward.service` (loopback SSH forwards).

## Sequence

1. Roll out compose on Mercury (`scripts/rollout-open-webui.sh` or container-services API).
2. Install the auth gate (`deploy/forge-auth-gate`) with `FORGE_AUTH_GATE_MODE=webui`, public origin `https://webui.forgedc.net`, upstream `http://127.0.0.1:19808`, listen `127.0.0.1:19809`.
3. Apply the Mercury tunnel and DNS (`apply-cf-webui-tunnel.sh`).
4. Restart the Lenses gateway on Mercury after gateway `return_to` / redeem changes so `login.forgedc.net` can finish on `webui.forgedc.net`.

## Granite backends (unchanged host)

Account-plane Chromium, web bridges, and forge-gateway still run on Granite loopback. Mercury user `leo` reaches them with `forge-openwebui-granite-forward.service` (`deploy/open-webui/scripts/install-granite-backend-forwards.sh`): `127.0.0.1:18080`, `:9240`, and `:9241` forward over SSH Host `granite` (Cloudflare websocket `granite.forgedc.net/ssh`, user `administrator`). Do not add public DNS for those ports. The forward also listens on the Docker bridge addresses (`172.17.0.1` for `host.docker.internal`, plus the compose network gateway) so the Open WebUI container can reach Granite. A `401` from `http://host.docker.internal:18080/v1/models` inside `forge-open-webui` means that path is up and the gateway still requires its bearer.

Historical Granite UI notes (headless Chromium sign-in, bridge limits) follow. The UI process itself is no longer on Granite.

## Granite account plane

1. Keep account-plane units on Granite (`install-open-webui-account-plane.sh`). Do not point `webui.forgedc.net` back at Granite `:19808`.
2. Install account-plane units (`install-open-webui-account-plane.sh`). Default **`FORGE_OPEN_WEBUI_HEADLESS=1`**: **Chromium** (Google Chrome on Granite) runs `--headless=new` (no Granite GUI / no `DISPLAY=:0`).
3. **Sign-in without Granite GUI:** Granite runs headless Chromium. Preferred: the Fleet CDP stream sign-in used by the Market edge plane (`granite-market-edge-plane.md`), targeting the account's CDP port (`:9230` chatgpt, `:9231` gemini). **Bootstrap only — operator-granted SSH:** `deploy/open-webui/scripts/granite-open-webui-auth-laptop.sh chatgpt-primary` opens an SSH tunnel `:19230`/`:19231` → Granite and a Playwright Inspector on the laptop for OAuth; run it only when the operator explicitly grants SSH in that message (see `granite-no-ssh-without-permission.mdc`). Alternative without SSH: pack profile (`pack-open-webui-edge-profile.sh` + Fleet upload). Use dedicated `~/.config/chromium-granite-*` dirs — not operator Edge/Market profiles.
4. Register bridge URLs in Open WebUI admin (see deploy README §4). The bridge bearer per account is in `~/.config/forge-open-webui/bridge-<slug>.env` on Granite (created 0600 by the installer; required by default — `FORGE_WEB_BRIDGE_REQUIRE_BEARER=1`).
5. **Forge LLM catalog in the UI:** run `deploy/open-webui/scripts/install-openwebui-forge-llm-connections.sh`, restart forge-gateway + Open WebUI (README §4b). Gateway bearer is in `~/.config/forge-open-webui/forge-llm-gateway.env`; Ollama direct API stays disabled in Open WebUI.

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

## Chat identity forwarded to backends (forge-2b follow-ups)

`compose.yaml` sets `ENABLE_FORWARD_USER_INFO_HEADERS=true` (Open WebUI core setting, no fork). On every chat completion Open WebUI then adds `X-OpenWebUI-Chat-Id` and `X-OpenWebUI-User-{Id,Name,Email,Role}` to the request it sends to OpenAI-compatible connections. The forge-2b shim uses the chat id as its conversation key so an elliptical follow-up ("And in the public re-run?") can be read against the previous turn; it keeps a **hash** of the user id only and never stores the name or the email. Direct API callers get the same behaviour with an `X-Forge-Chat-Id` header. Override with `ENABLE_FORWARD_USER_INFO_HEADERS=false` in `.env` to switch the forwarding off; apply compose changes with `POST /v1/container-services/open-webui/start` (recreates the container, a few seconds of downtime) — rolled out 2026-11-06 with Fleet 0.3.211.

## Fleet capability follow-up

The production sign-in path must not need SSH. Open item: extend the Market edge-plane CDP stream (`forge_fleet` edge routes) to the Open WebUI account ports `:9230`/`:9231` so the operator completes OAuth/Turnstile from the laptop browser through Fleet. Until then `granite-open-webui-auth-laptop.sh` stays bootstrap-only and refuses to run without `FORGE_OPERATOR_GRANTED_SSH=1`.

## References

- [Granite operator boundary](../design/granite-operator-boundary.md)
- [Granite Market edge plane](granite-market-edge-plane.md) (CDP stream sign-in pattern)
- [Unified Caddy](../build-201/04-caddy-unified-granite.md)
