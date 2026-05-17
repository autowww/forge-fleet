# Examples — Remote update automation

Two halves:

| Mechanism | Notes |
|-----------|-------|
| **`scripts/update-fleet.sh`** | Maintainer workstation semver bump → **`git push`** → optional **`--remote-git-self-update`** (**[Operate 301](../operate-301/05-upgrade-release-and-remote-update.md)**) |
| **`POST /v1/admin/git-self-update`** | API-triggered **`git pull`** against **`FLEET_GIT_ROOT`** (**`/opt`** caveat → **[HTTP API](../reference/01-http-api-reference.md)**) |

Never paste bearer tokens into shell history on shared hosts—prefer **`ENV`** files sourced ephemerally.

## Purpose

Contrast maintainer **`update-fleet.sh`** flows with in-process **`POST /v1/admin/git-self-update`**.

## Prerequisites

**`FLEET_GIT_ROOT`**, git credentials on the Fleet host, and admin bearer token for the API path.

## Copy-paste steps

Follow **[Upgrade / release / remote update](../operate-301/05-upgrade-release-and-remote-update.md)** and HTTP reference for **`postAdminGitSelfUpdate`**.

## Expected output

**200/400** JSON per policy; **`400`** with **`system_root_install_command`** is expected on **`/opt`** installs—run the printed **`sudo`** step.

## Error handling

Capture JSON **`error`** / **`detail`**; see **[error-handling.md](error-handling.md)**.

## Security notes

Protect **`FLEET_BEARER_TOKEN`** and host git credentials; audit who can reach **`/v1/admin/*`**.

## Related

- **[HTTP API](../reference/01-http-api-reference.md)**
- **[Operate 301 — Upgrade](../operate-301/05-upgrade-release-and-remote-update.md)**

## Validation status

- OpenAPI operation **`postAdminGitSelfUpdate`** (**[`../schemas/openapi.json`](../schemas/openapi.json)**); optional JSON body is an open object.
- Docs copy checked by **`check-docs-examples.py`** where snippets embed Fleet URLs.
