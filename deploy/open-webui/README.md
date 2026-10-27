# Open WebUI on Granite (Fleet-managed)

Pinned image `ghcr.io/open-webui/open-webui:v0.12.3`. Separate Postgres + file volumes from Market Studio. UI is exposed on a **dedicated hostname** via unified Caddy (`OPEN_WEBUI_SITE_ADDRESS`), not `/v1/app-gateways/`.

## Fleet compliance

- Deploy with `scripts/rollout-open-webui.sh` or `POST /v1/container-services` + `…/start` (compose root = this folder).
- Do not copy laptop `~/.config/microsoft-edge`. Market harvest stays on `microsoft-edge-granite-market` CDP `:9222`.
- Secrets only in Granite `.env` (from `.env.example`).

## 1. Volumes and compose

```bash
cd deploy/open-webui
cp .env.example .env
# set WEBUI_SECRET_KEY, POSTGRES_PASSWORD, WEBUI_URL, OPEN_WEBUI_SITE_ADDRESS
../../scripts/rollout-open-webui.sh
```

Register with Fleet (example):

```bash
curl -sS -X POST "$FORGE_FLEET_BASE_URL/v1/container-services" \
  -H "Authorization: Bearer $FORGE_FLEET_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "open-webui",
    "type_id": "service",
    "compose_root": "'"$HOME/.local/share/forge-fleet/deploy/open-webui"'",
    "compose_files": ["compose.yaml", "compose.granite.yaml"],
    "label": "Open WebUI"
  }'
curl -sS -X POST "$FORGE_FLEET_BASE_URL/v1/container-services/open-webui/start" \
  -H "Authorization: Bearer $FORGE_FLEET_BEARER_TOKEN"
```

## 2. Streaming edge (hostname B)

On Granite, set in `~/.config/forge-fleet/forge-fleet.env`:

- `OPEN_WEBUI_SITE_ADDRESS=webui.your-domain`
- `OPEN_WEBUI_UPSTREAM_PORT=19808` (match `OPEN_WEBUI_HOST_PORT`)

Re-run unified Caddy installer from forge-fleet:

```bash
cd forge-fleet
LAYOUT=user ./scripts/install-caddy-fleet-ollama-unified.sh --non-interactive
```

Point DNS/tunnel at the same origin as Fleet. Do **not** use `register_edge_route` for the UI.

## 3. Signed-in ChatGPT / Gemini (web accounts)

One Edge profile + one loopback bridge per account:

```bash
cp accounts.example.json accounts.json
./scripts/install-open-webui-account-plane.sh
systemctl --user start forge-open-webui-edge-chatgpt-primary.service
systemctl --user start forge-open-webui-bridge-chatgpt-primary.service
# repeat for gemini-primary
```

Sign in through the **Fleet CDP stream** for each Granite profile (same pattern as [granite-market-edge-plane.md](../../docs/operate/granite-market-edge-plane.md)).

Install bridge deps on Granite host:

```bash
pip install -e deploy/open-webui/bridge
pip install -e forge-lcdl[playwright]
playwright install chromium
```

## 4. Register models in Open WebUI (admin)

After bridges listen on loopback:

1. Open **hostname B** → Admin → **Connections** → OpenAI.
2. Add one connection per bridge:
   - **API URL:** `http://127.0.0.1:9240/v1` (ChatGPT pilot) and `http://127.0.0.1:9241/v1` (Gemini pilot). From inside the container use `http://host.docker.internal:9240/v1` in `.env` as `OPENAI_API_BASE_URLS` (semicolon-separated).
   - **API key:** optional; set `FORGE_WEB_BRIDGE_BEARER` on the bridge unit if used.
3. In chat, use the model picker:
   - **Provider:** `granite-chatgpt-primary` / `granite-gemini-primary` (session default — whatever is selected in Chromium).
   - **Web UI variants:** `granite-chatgpt-primary.gpt-4o`, `granite-gemini-primary.fast`, etc. (from `config/web-model-catalog.json`, merged with live CDP scrape when signed in). No Open WebUI extension required.
4. Verify: send a short prompt; assistant text should come from the signed-in Granite browser session.

## 5. Upstream git workflow

- `autowww/open-webui` `main` mirrors upstream tags only.
- Custom code on `forge` branch; image pin in compose.
- This deploy folder lives in **forge-fleet** (not in the Open WebUI fork).
