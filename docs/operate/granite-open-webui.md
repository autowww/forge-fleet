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
4. **Sign-in without Granite GUI (laptop):** Granite runs headless Chromium. On the **laptop**, run `deploy/open-webui/scripts/granite-open-webui-auth-laptop.sh chatgpt-primary` (then `gemini-primary`) — SSH tunnel `:19230`/`:19231` → Granite `:9230`/`:9231`, Playwright Inspector opens on the laptop for OAuth. Alternative: pack profile (`pack-open-webui-edge-profile.sh` + Fleet upload). Use dedicated `~/.config/chromium-granite-*` dirs — not operator Edge/Market profiles.
4. Register bridge URLs in Open WebUI admin (see deploy README §4).

## References

- [Granite operator boundary](../design/granite-operator-boundary.md)
- [Granite Market edge plane](granite-market-edge-plane.md) (CDP stream sign-in pattern)
- [Unified Caddy](../build-201/04-caddy-unified-granite.md)
