# Learn 101 — Operator apt install (no git)

**Outcome:** Fleet user cockpit on a fresh **Ubuntu 24.04 (noble)** machine without `git clone`.

**Audience:** laptop operators and mesh cockpits. Contributors still use **[git install](04-git-install.md)**.

## Placeholders

| Placeholder | Default when unset |
|-------------|-------------------|
| `<FLEET_APT_REPO_URL>` | `https://packages.forgesdlc.com/fleet/ubuntu` |
| `<FLEET_APT_SUITE>` | `noble` |

Override for staging:

```bash
export FORGE_APT_BASE_URL="https://<FLEET_APT_REPO_HOST>/fleet/ubuntu"
```

## Laptop (user package, port 18766)

```bash
curl -fsSL "${FORGE_APT_BASE_URL:-https://packages.forgesdlc.com/fleet/ubuntu}/install.sh" \
  -o /tmp/forge-fleet-install.sh
bash /tmp/forge-fleet-install.sh --user
land-fleet setup-user
curl -fsS http://127.0.0.1:18766/v1/health
```

With Docker (optional local worker):

```bash
bash /tmp/forge-fleet-install.sh --user --with-docker
```

## System node (port 18765)

```bash
sudo bash /tmp/forge-fleet-install.sh --system --with-docker
curl -fsS http://127.0.0.1:18765/v1/health
```

## Next step

Connect to an existing remote Fleet: **[08-connect-remote-fleet.md](08-connect-remote-fleet.md)**.
