# Install forge-fleet from a git clone

Use this path when you bring the repo onto a **new or remote machine** with `git clone` (not when you already develop in `~/Code` and rsync from there — that flow stays **`install-update.sh`**).

## Quick start (systemd system unit, `/opt/forge-fleet`, port 18765)

```bash
git clone <YOUR_FORGE_FLEET_REPO_URL> forge-fleet
cd forge-fleet
chmod +x git-install.sh   # if your clone did not preserve +x
./git-install.sh
```

`git-install.sh`:

1. Runs **`git submodule update --init --recursive`** so **`kitchensink/`** and **`blueprints/`** exist (required by **`install-update.sh`**).
2. Runs **`sudo ./install-update.sh`**, which rsyncs this clone to **`/opt/forge-fleet`**, installs/refreshes **`/etc/systemd/system/forge-fleet.service`**, creates **`/etc/forge-fleet/forge-fleet.env`** from the example if missing, and **restarts** `forge-fleet.service`.

Then:

- Set **`FLEET_BEARER_TOKEN`** in **`/etc/forge-fleet/forge-fleet.env`** when not binding loopback-only (see main **README**).
- Ensure the **`forge-fleet`** user exists and is in the **`docker`** group if you use Docker jobs (see comments in **`systemd/forge-fleet.service`**).
- First time the unit may not be enabled:  
  `sudo systemctl enable --now forge-fleet.service`

## User-level install (no `/opt`, systemd --user)

```bash
cd forge-fleet
./git-install.sh --user
```

Uses **`install-user.sh`** (defaults include port **18766** and data under XDG paths). For login-less boot, run once: **`loginctl enable-linger $USER`**.

## Prepare only (submodules; no sudo)

```bash
./git-install.sh --prepare-only
```

Then run **`sudo ./install-update.sh`** yourself when ready.

## Forwarding options

Anything after **`--`** is passed through to **`install-update.sh`** or **`install-user.sh`**:

```bash
./git-install.sh -- --dry-run
./git-install.sh -- --no-restart
```

## Clone with submodules in one step (optional)

```bash
git clone --recurse-submodules <URL> forge-fleet
cd forge-fleet
./git-install.sh --prepare-only   # optional; git-install will run submodule update anyway
./git-install.sh
```

## Troubleshooting

| Problem | What to check |
|--------|----------------|
| `missing kitchensink/` | Run `git submodule update --init --recursive` or clone with `--recurse-submodules`. |
| `install-update` fails on `rsync` | Install `rsync` (`apt install rsync` / `dnf install rsync`). |
| `FLEET_SRC and FLEET_DEST are the same` | Do not set **`FLEET_DEST`** to your clone path; production lives under **`/opt/forge-fleet`** by default. |
| Docker jobs fail | Dedicated user **`forge-fleet`** needs the **`docker`** group; see **`systemd/forge-fleet.service`** header. |
| HTTPS submodule prompts | Use SSH remotes for submodules or cache credentials for HTTPS. |

## Related scripts

| Script | Role |
|--------|------|
| **`git-install.sh`** | Clone → submodules → **`install-update.sh`** or **`install-user.sh`**. |
| **`install-update.sh`** | Rsync checkout → **`FLEET_DEST`**, systemd system unit + **`forge-fleet-telemetry.timer`**, restart. |
| **`install-user.sh`** / **`setup.sh`** | User-level tree + systemd --user + **`forge-fleet-telemetry.timer`** (SQLite samples when HTTP is stopped). |
| **`scripts/update-fleet.sh`** | Bump version, commit, push, then **`install-update.sh`** (system install); if **`~/.config/systemd/user/forge-fleet.service`** exists, also **`update-user.sh`** unless **`--no-user`**. |
