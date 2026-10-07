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

## Wedged dependents (bounded probes)

Every coordinator probe against a dependent must be **time-bounded**. A wedged service (worker pool exhausted, event loop blocked) still accepts TCP connections but never answers; an unbounded `curl -fsS` then blocks until the outer rollout timeout, which is exactly the state where a rollout is the only recovery path.

`scripts/rollout-forge-market-studio.sh` routes all studio probes through `_studio_curl` (`--connect-timeout 3 --max-time 10`, overridable via `FORGE_MARKET_STUDIO_CURL_CONNECT_TIMEOUT_SEC` / `FORGE_MARKET_STUDIO_CURL_TIMEOUT_SEC`). Rules:

1. prepare-stop unreachable → log `WARN` and continue (nothing to drain).
2. stop-readiness unreachable on **two consecutive** probes → treat as wedged, stop waiting, continue to the restart.
3. Pause/drain/resume helpers tolerate probe failure and fall through; they never block the rollout on a dead studio.

Measured incident (2026-10-07): a prod `market-studio` rollout spent 1800s inside `stop-readiness` polling against a wedged container and was killed by `FLEET_FORGE_MARKET_STUDIO_ROLLOUT_TIMEOUT_SEC`, leaving the container unrecovered.

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
