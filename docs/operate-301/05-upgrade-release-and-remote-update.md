# Operate 301 — Upgrade, release, and remote self-update

This page ties together **semver shipping**, **bare-metal refresh**, and the authenticated **`POST /v1/admin/git-self-update`** path so operators aren’t juggling three contradictory README excerpts.

```blueprint-diagram-ascii
key: linear
alt: Release branch versus remote git self-update
caption: Maintainers bump semver and push; remote hosts may pull via authenticated POST.
Maintainer clone -> update-fleet.sh -> git push
Operator client -> POST admin git-self-update -> Fleet host git pull
```

## Local maintainer workstation — ship Fleet

`./scripts/update-fleet.sh` (repo root):

- **`git submodule update --init --recursive`**, SemVer bump, commit **`chore(release)`**, **`git push`**
- optional **`sudo ./install-update.sh`** or **`./update-user.sh`** after push (layout-dependent)
- optional **`--remote-git-self-update`** → **`curl` POST** **`{FORGE_FLEET_BASE_URL}/v1/admin/git-self-update`** with bearer

Env hints: **`FORGE_FLEET_BASE_URL`**, **`FORGE_FLEET_BEARER_TOKEN`**, **`FLEET_REMOTE_GIT_SELF_UPDATE_URL`**. Overrides: **`--remote-url`**, **`--remote-bearer`**.

## Remote Fleet host semantics

Fleet must know **`FLEET_GIT_ROOT`** (tree without bare **`.git`**) so HTTP self-update can fast-forward cleanly. **`/opt/forge-fleet`** installs may reply **400** with **`system_root_install_command`**—operators must SSH and run that **sudo** line.

## Operators refreshing “this laptop” Fleet

Separate workflow: **`git pull --rebase`** in **`~/forge-fleet`**, **`./update-user.sh`**, **`systemctl --user restart forge-fleet.service`**. Workspace rules (“update service”) point here—not the semver release automation unless intentionally combined.

See also **[Architecture](03-architecture.md)** for systemd layout expectations and **[HTTP API](../reference/01-http-api-reference.md)** for the exact **`git-self-update`** response schema.
