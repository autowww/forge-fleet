# Granite — Postgres PG-A tuning (staged)

Apply NVDA-benchmark GUC packages to `forge-market-postgres` without SSH file surgery when Fleet has synced [forge-market-studio compose](../../../deploy/forge-market-studio/compose.yaml).

## Files (deploy tree)

| File | Role |
|------|------|
| `postgres-tuning.conf.disabled` | Default compose mount (no overrides) |
| `postgres-tuning-lite.conf` | Stage 1 restart |
| `postgres-tuning-full.conf` | Stage 2 restart |
| `postgres-tuning.conf` | Active file (copy from lite or full) |

Set in `.env`: `FORGE_MARKET_PG_TUNING_CONF=./postgres-tuning.conf` (or path to lite/full).

Tuning mounts to `/etc/postgresql/conf.d/99-forge-market-tuning.conf` (outside `PGDATA` so the entrypoint can `chown` data). One-time, append to `postgresql.conf`:

`include_if_exists = '/etc/postgresql/conf.d/99-forge-market-tuning.conf'`

(`scripts/ensure-postgres-tuning-include.sh` in the deploy folder.)

## Sequence

1. Backup pgdata / `fleet-rollout-backup.sh`.
2. `cp postgres-tuning-lite.conf postgres-tuning.conf`; `docker compose restart postgres` (prod compose project).
3. Verify `SHOW shared_buffers;` / market-app `/health`.
4. After soak: `cp postgres-tuning-full.conf postgres-tuning.conf`; restart postgres again.
5. Rerun forge-market bench tools in-container (see [granite-nvda-pipeline-benchmark.md](../../../forge-market/docs/perf/granite-nvda-pipeline-benchmark.md)).

Rollback: `cp postgres-tuning.conf.disabled postgres-tuning.conf` and restart postgres.

## Rollout backup failures (mistaken `postgres-tuning.conf` directory)

If pre-migrate `pg_dump` verification fails with a **bind-mount / docker cp** error, check the Granite deploy tree (`~/.local/share/forge-fleet/deploy/forge-market-studio`):

1. `postgres-tuning.conf` must be a **file**, not a directory — remove the directory and set `FORGE_MARKET_PG_TUNING_CONF=./postgres-tuning.conf.disabled` in `.env`.
2. If Postgres restart-loops with **flex scanner** errors on `99-forge-market-tuning.conf`, strip the `include_if_exists` line from the **pgdata** volume (`forge_market_studio_pgdata`) and recreate postgres (see `scripts/remediate-market-studio-pg-tuning-backup.sh`).
3. Take a manual verified dump: `scripts/fleet-rollout-backup.sh` (stdin `pg_restore --list` verify) or Fleet job per remediate script.
