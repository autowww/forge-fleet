# Granite operator boundary

Hard rule for **ff-granite-hosting-pdca**: Granite SSH is **only** for upgrading the Forge Fleet daemon when `POST /v1/admin/git-self-update` is insufficient (for example `system_install_requires_root`). All Market Studio deployment, data movement, image build, volume seeding, service lifecycle, edge routing, and cutover verification must go through **Fleet HTTP APIs**.

## Allowed paths

| Action | Allowed path |
|--------|--------------|
| Upgrade Fleet code | `POST /v1/admin/git-self-update` (preferred) or SSH **only** to run documented Fleet install/update (`git pull`, `./update-user.sh` / `install-update.sh`) when API returns `system_install_requires_root` |
| Deploy Market Studio stack | `POST /v1/container-services`, `POST …/start`, `POST /v1/admin/forge-market-studio-rollout` |
| Transfer Market data | `PUT /v1/migrations/{id}/data-bundle` + migration jobs |
| Build app image on Granite | Fleet job (`docker build`) or `POST /v1/container-templates/build` + image pull |
| Register HTTPS route | Fleet migration step `register_edge_route` (app gateway on the existing Fleet API hostname; no new Cloudflare tunnel) |
| Rollback | `POST …/stop`, re-run restore migration steps from same bundle |
| Debug | Read-only `journalctl`, `docker ps` **only when Fleet API status is insufficient** — no mutating commands |

## Forbidden on Granite SSH

- `scp`, `rsync`, manual `tar` extract for migration bundles
- Manual `docker compose` for Market Studio or market-related stacks
- Manual volume copies or volume surgery
- Manual Caddy / edge config edits for Market Studio routes
- Manual image build or registry push outside Fleet jobs
- Any mutating deploy or data command for Market Studio cutover

## Enforcement

- Requirement **R06** in [00-requirements-ledger.md](../prompts/ff-granite-hosting-pdca/00_shared/00-requirements-ledger.md)
- Phase prompts include operator **allowlist** / **denylist** sections
- `./scripts/ff-granite-hosting-pdca/check-granite-boundary.sh` greps operator runbooks for forbidden patterns (phase **FH65**)

## Reference

- Coordinator program: [ff-granite-hosting-pdca](../prompts/ff-granite-hosting-pdca/00-master-sequence.md)
- Fleet self-update: `./scripts/update-fleet.sh --remote-git-self-update`
