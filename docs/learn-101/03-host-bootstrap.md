# Fleet host bootstrap (OS dependencies)

**Audience:** Operators preparing a bare Linux host before Fleet install scripts. **Outcome:** Docker Engine (with buildx), Python **3.11+**, git, rsync, and curl are available. **Verify:** `docker info` succeeds; `python3 --version` is 3.11 or newer.

Use this guide on a **bare Linux host** (for example Ubuntu on a workstation) **before** [`git-install.sh`](../../git-install.sh) / [`install-update.sh`](../../install-update.sh) / [`install-user.sh`](../../install-user.sh). Those scripts install Forge Fleet itself (rsync to runtime tree, systemd); they do **not** install Docker or other OS packages.

Forge Fleet requires **Python 3.11+** (see [`pyproject.toml`](../../pyproject.toml) `requires-python`), **git**, **rsync**, and **curl** for a normal install-from-git flow. For `docker_argv` jobs, container templates, and managed compose services, you need a working **Docker Engine** CLI and daemon.

## 1. Base packages (Ubuntu / Debian)

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git rsync python3 python3-venv
```

Ensure `python3` is at least 3.11 (`python3 --version`). On older LTS releases, use **deadsnakes** or a distro release that ships 3.11+.

## 2. Docker Engine + BuildKit buildx (recommended)

`docker build` with BuildKit expects the **`docker-buildx-plugin`**. Ubuntu’s **`docker.io`** package alone often triggers *“BuildKit is enabled but the buildx component is missing”* on template builds. Prefer **Docker’s official apt repository** and these packages:

- `docker-ce`, `docker-ce-cli`, `containerd.io`
- `docker-buildx-plugin`, `docker-compose-plugin`

### Ubuntu

1. Remove conflicting **`docker.io`** / **`containerd`** if present (only if you intend to switch stacks):

   ```bash
   sudo apt-get remove -y docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc 2>/dev/null || true
   ```

2. Add Docker’s apt repo and install (see also [Install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)):

   ```bash
   sudo install -m 0755 -d /etc/apt/keyrings
   sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
   sudo chmod a+r /etc/apt/keyrings/docker.asc
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
   sudo apt-get update
   sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
   sudo systemctl enable --now docker
   ```

3. Add your operator user (or the dedicated `forge-fleet` system user) to the **`docker`** group, then **log out and back in** (or reboot) so group membership applies to systemd user sessions.

### Debian

Use [Install Docker Engine on Debian](https://docs.docker.com/engine/install/debian/) — same package names after adding Docker’s **debian** apt source.

### Alternative: legacy builder only (no buildx)

If you cannot install buildx, set **`FLEET_DOCKER_BUILDKIT=0`** in the Fleet environment file (see [`systemd/environment.example`](../../systemd/environment.example)) so template builds use the legacy Docker builder. See [`../build-201/02-container-templates.md`](../build-201/02-container-templates.md) for `FLEET_DOCKER_BUILDKIT` behavior.

## 3. User-level Fleet (systemd --user)

If you use [`./git-install.sh --user`](04-git-install.md) (see that doc), enable lingering so the service can start without an interactive login:

```bash
loginctl enable-linger "$USER"
```

See [`03-git-install.md`](04-git-install.md) for ports (**18766** user vs **18765** system) and data directories.

## 4. Install Forge Fleet from git

After Docker and base tools are ready:

```bash
git clone --recurse-submodules <YOUR_FORGE_FLEET_REPO_URL> forge-fleet
cd forge-fleet
chmod +x git-install.sh   # if needed
./git-install.sh          # system /opt install, or: ./git-install.sh --user
```

Configure **`FLEET_BEARER_TOKEN`** (and any other variables) in:

- System install: **`/etc/forge-fleet/forge-fleet.env`**
- User install: **`~/.config/forge-fleet/forge-fleet.env`**

Template: [`systemd/environment.example`](../../systemd/environment.example).

Full clone and systemd narrative: **[03-git-install.md](04-git-install.md)**.

## 5. Incremental host steps after upgrades

When you pull a newer Fleet release, **SQLite schema migrations** run automatically inside the server. **Host-level** steps (apt, new env vars) are listed per release in **[CHANGELOG.md](../../CHANGELOG.md)** under **`### Host operator`**, and in machine-readable form in **[`docs/host-operator-steps.json`](../host-operator-steps.json)**.

From a clone, print applicable host commands between two versions (read-only; does not execute them):

```bash
./scripts/fleet-host-upgrade-hints.sh --from 0.3.40 --to 0.3.49
```

Omit **`--to`** to use the version from **`pyproject.toml`** in this checkout. Omit **`--from`** and pass **`--discover-from`** to read the running version from **`GET /v1/version`** using **`FORGE_FLEET_BASE_URL`** and **`FORGE_FLEET_BEARER_TOKEN`** when your server requires auth.
