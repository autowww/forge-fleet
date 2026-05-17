# Operate 301 — Observability and SLOs

**Audience:** operators wiring Fleet into existing monitoring.  
**Outcome:** know which endpoints and logs are **signal-rich** without pretending Fleet is a full APM stack.

## Health and version

| Endpoint | Use |
| --- | --- |
| **`GET /v1/health`** | Live host snapshot (CPU/RAM/load) when bearer policy allows—good **liveness** probe |
| **`GET /v1/version`** | **SemVer + git** metadata—pair with release cadence |

Treat **`200`** JSON as “process up”; interpret inner fields per **[HTTP API reference](../reference/01-http-api-reference.md)**.

## Telemetry

| Endpoint | Use |
| --- | --- |
| **`GET /v1/telemetry?period=…`** | Historical samples—use for **trend** dashboards, not per-request tracing |

## Logs

| Source | What to watch |
| --- | --- |
| **journald** (`forge-fleet.service`) | SQLite errors, Docker spawn failures, auth denials |
| **Job `stderr_tail`** | Per-job failures—via **`GET /v1/jobs/{id}`** |

## Suggested SLIs

1. **Availability** — share of **`GET /v1/health`** checks returning **200** during window.
2. **Job success rate** — fraction of jobs reaching **`completed`** vs **`failed`** (derive from **`GET /v1/admin/snapshot`** or your metrics exporter).
3. **Time-to-first-log** — time from **`queued`** → **`running`** (Docker/socket health).

## Alerts (examples)

- Health probe fails **N** times consecutively.
- SQLite **“database is locked”** spikes (disk/IO contention).
- **Docker not found** / runner spawn errors exceed baseline (**[Troubleshooting](04-troubleshooting.md)**).

## Capacity

- Watch **`FLEET_DATA_DIR`** disk—SQLite + template build caches grow with job churn.
- Large workspace uploads: see workspace profile limits in **[Workspace upload](../build-201/01-workspace-upload.md)**.

## Related

- **[Architecture](03-architecture.md)**  
- **[Operations runbook](02-operations-runbook.md)**
