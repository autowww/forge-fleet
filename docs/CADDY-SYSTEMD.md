# Caddy in front of Fleet (systemd, start at boot)

**Default in this repo:** Caddy listens on **HTTP `http://0.0.0.0:18766/`** (all interfaces, no TLS) and proxies to Fleet on **`127.0.0.1:18765`**, injecting **`Authorization: Bearer $FLEET_BEARER_TOKEN`**.

## One-shot install (systemd permanent service)

1. Install Caddy and ensure user **`caddy`** exists (`apt install caddy` / `dnf install caddy`).

2. Put Forge Fleet on **loopback** with bearer enforced (drop-in), then run the installer from your checkout (or `/opt/forge-fleet` after `install-update.sh`):

```bash
sudo systemctl edit forge-fleet.service
```

Use this override:

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/python3 -m fleet_server --host 127.0.0.1 --port 18765 --data-dir /var/lib/forge-fleet
Environment=FLEET_ENFORCE_BEARER=1
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart forge-fleet.service
```

3. **Install Caddy wrapper + enable systemd** (replace the token with the same value as in `/etc/forge-fleet/forge-fleet.env`):

```bash
FLEET_BEARER_TOKEN='DellPrecisionFleet' sudo -E bash /opt/forge-fleet/scripts/install-forge-fleet-caddy-systemd.sh
```

If you are still on a **git checkout** (not `/opt` yet):

```bash
cd /path/to/forge-fleet
FLEET_BEARER_TOKEN='DellPrecisionFleet' sudo -E ./scripts/install-forge-fleet-caddy-systemd.sh
```

This writes **`/etc/forge-fleet/Caddyfile`**, **`/etc/forge-fleet/caddy.env`**, **`/etc/systemd/system/forge-fleet-caddy.service`**, runs **`systemctl daemon-reload`**, **`enable`**, and **`restart`** **`forge-fleet-caddy`**.

Clients: **`http://<host>:18766/`** (and **`/admin/`**, **`/v1/…`** through Caddy).

## Files

| Path | Role |
|------|------|
| `systemd/Caddyfile.forge-fleet.example` | Copied to `/etc/forge-fleet/Caddyfile` |
| `systemd/forge-fleet-caddy.service` | Installed unit **`forge-fleet-caddy.service`** |
| `scripts/install-forge-fleet-caddy-systemd.sh` | Idempotent-ish install helper |

## TLS later

Edit **`/etc/forge-fleet/Caddyfile`**: use a hostname block and remove plain **`:18766`** when you want HTTPS and Let’s Encrypt (see [Caddy docs](https://caddyserver.com/docs/automatic-https)).

## Conflicts with a stock `caddy.service`

Disable the distro unit if it also binds **18766**, or merge this site block into **`/etc/caddy/Caddyfile`** and use the stock **`caddy.service`** instead of **`forge-fleet-caddy.service`**.
