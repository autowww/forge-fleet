# Learn 101 — Connect to a remote Fleet (Cloudflare)

**Outcome:** your laptop Fleet (`127.0.0.1:18766`) can **view** a remote Fleet host through the admin dashboard, using a public HTTPS URL and bearer token — without storing secrets in the handbook or pasting them into Markdown.

**Audience:** operators after **[operator apt install](09-operator-apt-install.md)** or **[git install](04-git-install.md)**. **Time:** ~20 minutes.

## Placeholders (dual-wiki safe)

Use env vars or a secrets file — **never** commit live URLs or tokens into git or handbook source:

| Placeholder | Env var (typical) | Meaning |
|-------------|-------------------|---------|
| `<FLEET_PUBLIC_BASE_URL>` | `FORGE_FLEET_BASE_URL` | Public HTTPS origin of the remote Fleet API |
| `<FLEET_BEARER_TOKEN>` | `FORGE_FLEET_BEARER_TOKEN` | Bearer for remote `/v1/*` |
| `<FLEET_APT_REPO_URL>` | `FORGE_APT_BASE_URL` | Apt bootstrap base (see [09-operator-apt-install.md](09-operator-apt-install.md)) |
| `<FLEET_PUBLIC_HOSTNAME>` | `CADDY_SITE_ADDRESS` | TLS hostname on the server (no scheme) |

Handbook pages are **dual-wiki**: edit this `.md` file; run `python3 generator/build-site.py` in **forge-fleet-website** to refresh HTML.

## Architecture

```
Laptop (forge-fleet-user, :18766)
  └── /admin/ → local Fleet stores peer in remote-peers.json
        └── GET proxy → https://<FLEET_PUBLIC_BASE_URL>/v1/…  (via Cloudflare → Caddy → Fleet)
```

- The **browser** only talks to **local** Fleet.
- **Cloudflare Tunnel** runs on the **server**; laptops do not install `cloudflared` for read-only admin.
- Public `/admin/` is usually **blocked** at Caddy; use **local admin + Remote scope** instead.

## Step 1 — Local Fleet healthy

```bash
land-fleet health
# or
curl -fsS http://127.0.0.1:18766/v1/health
```

Or open **`http://127.0.0.1:18766/admin/`** → **Connect…** wizard → step **1 Local**.

## Step 2 — Register remote peer

Set env from your operator secrets file (example):

```bash
export FORGE_FLEET_BASE_URL="https://<FLEET_PUBLIC_HOSTNAME>"
export FORGE_FLEET_BEARER_TOKEN="<FLEET_BEARER_TOKEN>"
```

**CLI:**

```bash
land-fleet join \
  --coordinator "${FORGE_FLEET_BASE_URL}" \
  --enroll-token "${FORGE_FLEET_BEARER_TOKEN}" \
  --label "$(hostname -s)"
```

**Admin UI:** `/admin/` → **Connect…** → steps **2 Remote** and **3 Test** (Save → Probe → **View remote dashboard**).

**API:**

```bash
curl -fsS -X PUT "http://127.0.0.1:18766/v1/remote-peers/remote-worker" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg url "${FORGE_FLEET_BASE_URL}" \
    --arg tok "${FORGE_FLEET_BEARER_TOKEN}" \
    '{label:"Remote Fleet", base_url:$url, bearer_token:$tok}')"
```

## Step 3 — Verify probe

```bash
curl -fsS -X POST "http://127.0.0.1:18766/v1/remote-peers/remote-worker/probe"
```

Expect `"ok": true` and Fleet health JSON in the response.

Switch scope in admin (**Fleet scope** dropdown) to read snapshot, telemetry, and jobs **read-only**.

## Step 4 — Publishing a server through Cloudflare (root)

Only when **this machine** is the public Fleet host. The **Connect…** wizard step **4 Edge** copies the same recipe.

1. **DNS / Cloudflare** — public hostname `<FLEET_PUBLIC_HOSTNAME>` in your zone.
2. **`cloudflared`** on the server — install package, `cloudflared service install <CLOUDFLARE_TUNNEL_TOKEN>`, route hostname to `http://127.0.0.1:<CADDY_PORT>` (default **18767**).
3. **Unified Caddy** — must route `/v1/health` to Fleet before Ollama. See **[Unified public edge](../build-201/04-caddy-unified-granite.md)**.
4. **Verify** from any client:

```bash
curl -fsS -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
  "${FORGE_FLEET_BASE_URL}/v1/health"
```

Fleet does **not** create Cloudflare tunnels via API today; tunnel tokens come from the Cloudflare Zero Trust dashboard.

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| Probe `upstream_unreachable` | Wrong URL, tunnel down, or firewall |
| `/v1/health` → plain `Unauthorized` (12 bytes) | Caddy sends health to Ollama — fix unified routing |
| `/v1/health` → JSON `unauthorized` | Bearer mismatch vs server `FLEET_BEARER_TOKEN` |
| Public `/admin/` → 403 | Expected — use laptop admin + remote scope |

## Related

| Topic | Doc |
|-------|-----|
| Admin tour + Connect wizard | **[07-admin-dashboard-and-studio.md](07-admin-dashboard-and-studio.md)** |
| Apt install | **[09-operator-apt-install.md](09-operator-apt-install.md)** |
| Caddy + Cloudflare routing | **[04-caddy-unified-granite.md](../build-201/04-caddy-unified-granite.md)** |
| Mesh program (future job forward) | **ff-fleet-mesh-pdca** assumptions |
