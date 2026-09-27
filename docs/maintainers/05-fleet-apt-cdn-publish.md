# Fleet apt packages — CDN publish (maintainers)

**Policy:** Git holds **source only**. Fleet `.deb` files and the apt repository index are published **only** to:

`https://packages.forgesdlc.com/fleet/ubuntu/`

(Firebase Hosting site **`forge-packages`**, project **`fleet-2f1d3`**.)

Do **not** attach `.deb` files to GitHub Releases or use release assets as an install channel.

## Publish after a semver ship

1. From **`forge-fleet`** (version in `pyproject.toml` matches the release you are publishing):

   ```bash
   ./scripts/publish-and-deploy-fleet-apt-cdn.sh
   ```

   Or split: **`./scripts/publish-fleet-apt.sh`** then **`firebase deploy`** from **`forge-packages-website`**.

2. Before any git commit, CI runs **`./scripts/check-no-package-artifacts-in-git.sh`** — never commit **`dist/`** or **`.deb`** files.

3. Verify the CDN index lists the new version:

   ```bash
   curl -fsS https://packages.forgesdlc.com/fleet/ubuntu/dists/noble/main/binary-amd64/Packages | grep -A1 '^Package: forge-fleet$'
   ```

4. On **apt** production hosts (e.g. Granite), bump via Fleet API — **not** `git-self-update`:

   ```bash
   curl -sS -X POST "${FORGE_FLEET_BASE_URL}/v1/admin/upgrade" \
     -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
     -H "Content-Type: application/json" \
     -d '{"mode":"upgrade"}'
   ```

## CI (optional)

Workflow **Publish Fleet apt CDN** (`.github/workflows/publish-fleet-apt.yml`) deploys the same Hosting tree when the repo secret **`FIREBASE_TOKEN`** is set (`firebase login:ci`). It does **not** upload binaries to GitHub.

## Remote operators

Install/bootstrap: [Learn 101 — Operator apt install](../learn-101/09-operator-apt-install.md).
