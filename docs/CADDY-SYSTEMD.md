# Caddy in front of Fleet (systemd)

Primary installer (interactive prompts for layout, bearer, ports; Ubuntu `apt` for Caddy):

```bash
./scripts/install-caddy-fleet.sh
```

From **`$HOME`** (clone at `~/Code/forge-fleet`):

```bash
bash "$HOME/Code/forge-fleet/scripts/install-caddy-fleet.sh"
```

**Non-interactive** (e.g. remote):

```bash
# User Fleet (systemctl --user): Fleet 127.0.0.1:18766, Caddy :18767
LAYOUT=user FLEET_BEARER_TOKEN='your-token' bash ./scripts/install-caddy-fleet.sh --non-interactive

# System Fleet (sudo): upstream 127.0.0.1:18765, Caddy :18766
LAYOUT=system FLEET_BEARER_TOKEN='your-token' sudo -E bash ./scripts/install-caddy-fleet.sh --non-interactive
```

Optional env: `FLEET_UPSTREAM_HOST` `FLEET_UPSTREAM_PORT` `CADDY_PUBLIC_PORT` `INSTALL_CADDY_APT=0` (skip apt if Caddy already installed).

Legacy wrappers (same as `--non-interactive`): `scripts/install-forge-fleet-caddy-user-systemd.sh`, `scripts/install-forge-fleet-caddy-systemd.sh`.

---

## User Fleet (`install-user.sh`)

- Fleet: **`127.0.0.1:18766`** by default.
- Caddy: **`http://0.0.0.0:18767/`** by default (change in prompts or env).
- Config: **`~/.config/forge-fleet/forge-fleet.env`**, **`~/.config/forge-fleet/Caddyfile.caddy-fleet`**, **`~/.config/systemd/user/forge-fleet-caddy.service`**.
- Add **`FLEET_ENFORCE_BEARER=1`** when prompted so `/v1/*` checks bearer behind Caddy.
- Headless boot: **`loginctl enable-linger "$USER"`** once.

---

## System Fleet (`/opt`, `forge-fleet.service`)

- Put Fleet on loopback with **`systemctl edit forge-fleet.service`** (see below), then run installer with **layout 2** or `LAYOUT=system`.
- Writes **`/etc/forge-fleet/Caddyfile`**, **`/etc/forge-fleet/caddy.env`**, **`/etc/systemd/system/forge-fleet-caddy.service`**.

Drop-in for Fleet (loopback + enforce bearer):

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/python3 -m fleet_server --host 127.0.0.1 --port 18765 --data-dir /var/lib/forge-fleet
Environment=FLEET_ENFORCE_BEARER=1
```

---

## TLS later

Use a hostname site block in the Caddyfile and remove plain `:port` when you want HTTPS ([Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https)).

## Stock `caddy.service`

Disable it if it conflicts on the same port, or merge the site block into **`/etc/caddy/Caddyfile`** and use the distro unit instead of **`forge-fleet-caddy.service`**.
