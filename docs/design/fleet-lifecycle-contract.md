# Fleet cooperative upgrade lifecycle

Fleet and Forge HTTP services cooperate during upgrades via **prepare-stop** and **stop-readiness** endpoints.

## Paths

| Service | prepare-stop | stop-readiness | resume |
|---------|--------------|----------------|--------|
| Fleet | `POST /v1/lifecycle/prepare-stop` | `GET /v1/lifecycle/stop-readiness` | `POST /v1/lifecycle/resume` |
| Other Forge HTTP | `POST /api/lifecycle/prepare-stop` | `GET /api/lifecycle/stop-readiness` | `POST /api/lifecycle/resume` |

## Coordinator flow

1. Operator `POST /v1/admin/upgrade` (or `package-upgrade` for apt channel).
2. Fleet sets `draining=true`, POST prepare-stop to dependents.
3. Poll GET stop-readiness until all `stop_allowed: true` or timeout.
4. Apply update (git pull, apt signal + root timer, or restart).
5. Clear drain; dependents may receive resume.

## Response fields

See JSON schemas under `docs/schemas/lifecycle-*.schema.json`.

## Shared library

`forge_lcdl.lifecycle` provides `DrainingState`, blocker builders, and readiness payloads for vendored consumers.

## SLO targets

| Mode | Budget |
|------|--------|
| update | ≤10s Fleet HTTP unavailable |
| upgrade | ≤60s end-to-end (includes root apt timer granularity) |

## Apt channel

User Fleet writes `upgrade-request.json`; root `forge-fleet-apt-upgrade.timer` (every minute) runs `apt-get install` and restarts the unit.
