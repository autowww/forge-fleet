# Forge Fleet admin — Overview & release identity (design)

This document captures **what “broken” means** for `/admin/` → **Overview**, how release identity is supposed to work, and how we keep it from regressing (Playwright + install scripts + runtime fallbacks).

## Two different failure classes

1. **Release / drift visibility (software contract)**  
   When **`meta.version.git_sha`** is missing, the admin header shows *“No git SHA from server — cannot compare to GitHub.”* Operators lose the **Update Fleet** / drift signal even though HTTP and jobs may be fine. This has happened repeatedly on **rsync installs** (`install-user.sh` / `install-update.sh`) because the runtime tree **excludes `.git/`** and **`FLEET_GIT_SHA`** was not always set.

2. **Host saturation (capacity / environment)**  
   High **CPU %**, **load %**, or **temperature** (e.g. 90°C+) on the Overview tiles reflect the **machine under Fleet**, not a bad Fleet HTTP handler. Mitigations are operational: fewer concurrent jobs, better cooling, CPU limits on heavy containers, scheduling, etc. **Do not** treat a hot CPU tile alone as “Fleet code is broken” unless the service is also failing health checks or returning errors.

3. **Overview KPI layout (horizontal tile row)**  
   When **`#fleet-tiles`** is not a **flex row**, the CPU / thermal / RAM / load tiles render as a **tall vertical stack** on the left with empty space on the right — operators read this as “design broken.” Typical causes: **`GET /admin/ks/css/forge-fleet-admin.css`** failed (404, wrong reverse-proxy path, CSP), or a parent style forced **`flex-direction: column`** onto the row. **Mitigation:** `admin.html` ships a minimal **inline** fallback on **`#fleet-tiles.fleet-tile-row.fleet-one-row`** (`#fleet-overview-tile-row-fallback`); kitchensink **`forge-fleet-admin.css`** uses **`!important`** on **`#fleet-tiles.fleet-tile-row`** for **`display`** / **`flex-direction`**.

## Invariants (do not regress)

| Invariant | Mechanism |
|-----------|-----------|
| **`GET /v1/version`** exposes non-empty **`git_sha`** whenever the install can be tied to a git checkout | **`FLEET_GIT_SHA`** or **`SOURCE_GIT_COMMIT`** env; else **`git rev-parse --short HEAD`** on **`FLEET_GIT_ROOT`** when that path is a git checkout; else the same on the package parent directory **only if `FLEET_GIT_ROOT` is unset`** (dev clone). If **`FLEET_GIT_ROOT`** is set but not a git repo, Fleet does **not** guess from another path. |
| **`forge-fleet.env`** written on install refresh | **`scripts/set-fleet-git-root-in-env.sh`** sets **`FLEET_GIT_ROOT`** and **`FLEET_GIT_SHA`** from the **source** checkout used for rsync (that checkout still has `.git`). |
| Admin UI exposes machine-readable SHA state | **`#fleet-git-remote-row`** has **`data-fleet-git-sha-state="present"`** or **`missing`** after each snapshot (`admin.html`). |
| CI / dev guard | Playwright **`e2e/admin-status-overview.spec.ts`** + unit tests **`tests/test_versioning_git_sha.py`**. |
| **Overview tiles stay in one horizontal row** | **`#fleet-tiles`** has **`display: flex`**, **`flex-direction: row`** (computed style); at least **four** direct **`.fleet-tile`** children after snapshot. |

## Playwright scope

- **In scope:** `/v1/version` **`git_sha`**, version line contains **`git`**, **`data-fleet-git-sha-state`**, Overview tiles **`#fleet-cpu-value`** / **`#fleet-mem-val`** (sanity that snapshot + `renderTiles` ran); **computed `flex-direction` on `#fleet-tiles`** is **`row`**; **≥ 4** direct **`.fleet-tile`** children; first two tiles **left positions increase left-to-right** (not stacked).
- **Out of scope:** asserting specific temperatures or load numbers (environment-dependent).

## Operator checklist when Overview “looks bad”

1. If KPIs are a **vertical list**: DevTools → **Network** → confirm **`/admin/ks/css/forge-fleet-admin.css`** is **200** (not HTML error page). Fix reverse-proxy path mapping for **`/admin/ks/**`** or redeploy so **`kitchensink/css/forge-fleet-admin.css`** exists on the host.
2. Read **`#fleet-version-line`** and **`#fleet-git-remote-row`** — is SHA **present** and GitHub check reachable?
3. If thermals/load are extreme, inspect **Docker jobs**, **systemd** unit limits, and **hardware**; cross-check **`GET /v1/telemetry`** for sustained load.
4. After changing only **`forge-fleet.env`**, restart **`forge-fleet.service`** so the process picks up new **`FLEET_GIT_*`** values (runtime SHA probe still helps when **`FLEET_GIT_ROOT`** is set but **`FLEET_GIT_SHA`** was omitted).

## Related files

- `fleet_server/versioning.py` — SHA resolution and cache.
- `scripts/set-fleet-git-root-in-env.sh` — env file merge on install.
- `fleet_server/static/admin.html` — Overview tiles + **`data-fleet-git-sha-state`** + **`#fleet-overview-tile-row-fallback`** inline row styles.
- `kitchensink/css/forge-fleet-admin.css` (source repo **forgesdlc-kitchensink**) — full tile / chart styling; **`#fleet-tiles`** row **`!important`** guard.
- `e2e/start-fleet-server.sh` — Playwright local server (no bearer by default on loopback).
