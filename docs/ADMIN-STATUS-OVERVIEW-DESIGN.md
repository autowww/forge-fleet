# Forge Fleet admin — Overview & release identity (design)

This document captures **what “broken” means** for `/admin/` → **Overview**, how release identity is supposed to work, and how we keep it from regressing (Playwright + install scripts + runtime fallbacks).

## Two different failure classes

1. **Release / drift visibility (software contract)**  
   When **`meta.version.git_sha`** is missing, the admin header shows *“No git SHA from server — cannot compare to GitHub.”* Operators lose the **Update Fleet** / drift signal even though HTTP and jobs may be fine. This has happened repeatedly on **rsync installs** (`install-user.sh` / `install-update.sh`) because the runtime tree **excludes `.git/`** and **`FLEET_GIT_SHA`** was not always set.

2. **Host saturation (capacity / environment)**  
   High **CPU %**, **load %**, or **temperature** (e.g. 90°C+) on the Overview tiles reflect the **machine under Fleet**, not a bad Fleet HTTP handler. Mitigations are operational: fewer concurrent jobs, better cooling, CPU limits on heavy containers, scheduling, etc. **Do not** treat a hot CPU tile alone as “Fleet code is broken” unless the service is also failing health checks or returning errors.

## Invariants (do not regress)

| Invariant | Mechanism |
|-----------|-----------|
| **`GET /v1/version`** exposes non-empty **`git_sha`** whenever the install can be tied to a git checkout | **`FLEET_GIT_SHA`** or **`SOURCE_GIT_COMMIT`** env; else **`git rev-parse --short HEAD`** on **`FLEET_GIT_ROOT`** when that path is a git checkout; else the same on the package parent directory **only if `FLEET_GIT_ROOT` is unset`** (dev clone). If **`FLEET_GIT_ROOT`** is set but not a git repo, Fleet does **not** guess from another path. |
| **`forge-fleet.env`** written on install refresh | **`scripts/set-fleet-git-root-in-env.sh`** sets **`FLEET_GIT_ROOT`** and **`FLEET_GIT_SHA`** from the **source** checkout used for rsync (that checkout still has `.git`). |
| Admin UI exposes machine-readable SHA state | **`#fleet-git-remote-row`** has **`data-fleet-git-sha-state="present"`** or **`missing`** after each snapshot (`admin.html`). |
| CI / dev guard | Playwright **`e2e/admin-status-overview.spec.ts`** + unit tests **`tests/test_versioning_git_sha.py`**. |

## Playwright scope

- **In scope:** `/v1/version` **`git_sha`**, version line contains **`git`**, **`data-fleet-git-sha-state`**, Overview tiles **`#fleet-cpu-value`** / **`#fleet-mem-val`** (sanity that snapshot + `renderTiles` ran).
- **Out of scope:** asserting specific temperatures or load numbers (environment-dependent).

## Operator checklist when Overview “looks bad”

1. Read **`#fleet-version-line`** and **`#fleet-git-remote-row`** — is SHA **present** and GitHub check reachable?
2. If thermals/load are extreme, inspect **Docker jobs**, **systemd** unit limits, and **hardware**; cross-check **`GET /v1/telemetry`** for sustained load.
3. After changing only **`forge-fleet.env`**, restart **`forge-fleet.service`** so the process picks up new **`FLEET_GIT_*`** values (runtime SHA probe still helps when **`FLEET_GIT_ROOT`** is set but **`FLEET_GIT_SHA`** was omitted).

## Related files

- `fleet_server/versioning.py` — SHA resolution and cache.
- `scripts/set-fleet-git-root-in-env.sh` — env file merge on install.
- `fleet_server/static/admin.html` — Overview tiles + **`data-fleet-git-sha-state`**.
- `e2e/start-fleet-server.sh` — Playwright local server (no bearer by default on loopback).
