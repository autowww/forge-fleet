# Forge Fleet Granite hosting PDCA — master sequence

Composer **2.5** implements phases **FH00–FH05** (Wave GW-0), **FH10–FH18** (GW-1), **FH20–FH28** (GW-2), **FH30–FH38** (GW-3), **FH40–FH48** (GW-4), **FH50–FH59** (GW-5), and **FH60–FH70** (GW-6) for Fleet-hosted Market Studio on Granite.

**Requirements source:** [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md) (R01–R24)

**Operator boundary:** [granite-operator-boundary.md](../../design/granite-operator-boundary.md) — Granite SSH **only** for Fleet daemon upgrade.

Executor model: **Composer 2.5** (standard variant, not `-fast`).

| Wave | Phases | Theme |
|------|--------|-------|
| GW-0 | FH00–FH05 | Scaffold, boundary, repos |
| GW-1 | FH10–FH18 | Fleet managed compose platform |
| GW-2 | FH20–FH28 | Migration + data-transfer API |
| GW-3 | FH30–FH38 | forge-market Postgres + container |
| GW-4 | FH40–FH48 | forge-studio-shell + adoption |
| GW-5 | FH50–FH59 | forge-migrator wizard |
| GW-6 | FH60–FH70 | Granite cutover + closeout |

## Related programs

| Program | Repo | Phases | Theme |
|---------|------|--------|-------|
| **ff-granite-hosting-pdca** | forge-fleet | FH00–FH70 | Coordinator |
| fm-postgres-hosting-pdca | forge-market | FMH01–FMH08 | Extends FM-ENT-004/008 |
| fss-studio-shell-pdca | forge-studio-shell | FSS01–FSS06 | Generic Electron shell |
| fmigr-wizard-pdca | forge-migrator | FMI01–FMI10 | Wizard + recipes |

Sub-program phases are invoked from FH prompts via **Handoff** sections; coordinator closeout gates (FH18, FH28, FH38, FH59, FH70) require sub-gates green.

---

## GW-0 — Scaffold, boundary, repos

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FH00 | [FH00-pdca-scaffold.md](FH00-pdca-scaffold.md) | — | PDCA harness + master sequence |
| FH01 | [FH01-requirements-ledger.md](FH01-requirements-ledger.md) | R01–R24 | Ledger + granite boundary doc |
| FH02 | [FH02-forge-studio-shell-repo.md](FH02-forge-studio-shell-repo.md) | R11 | `autowww/forge-studio-shell` skeleton |
| FH03 | [FH03-forge-market-repo.md](FH03-forge-market-repo.md) | R12 | forge-market private + integration branch |
| FH04 | [FH04-forge-migrator-repo.md](FH04-forge-migrator-repo.md) | R10 | `autowww/forge-migrator` skeleton |
| FH05 | [FH05-gw0-closeout.md](FH05-gw0-closeout.md) | — | GW-0 gate; sub-program scaffolds stubbed |

---

## GW-1 — Fleet managed compose platform

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FH10 | FH10-managed-compose-refactor.md | R01, R16 | `managed_compose_service.py`; `forge_llm_service` re-export |
| FH11 | FH11-container-type-catalog.md | R01 | `forge_market_studio` in types catalog |
| FH12 | FH12-main-py-capability-guards.md | R01, R16 | Capability flags replace hard-coded `forge_llm` |
| FH13 | FH13-market-studio-compose-stack.md | R02 | `deploy/forge-market-studio/compose.yaml` |
| FH14 | FH14-compose-integration-tests.md | R16 | Mock compose tests; LLM regression |
| FH15 | FH15-container-service-api-docs.md | R17 | OpenAPI + `docs/build-201/08-managed-compose-services.md` |
| FH16 | FH16-market-image-build-job.md | R23 | Fleet job template for market image |
| FH17 | FH17-market-studio-rollout-api.md | R02, R23 | `POST /v1/admin/forge-market-studio-rollout` |
| FH18 | FH18-gw1-closeout.md | — | GW-1 gate; `forge_llm` + new type coexist |

**Handoff:** FH13 unblocks forge-market FMH05 (Dockerfile).

---

## GW-2 — Fleet migration + data-transfer API

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FH20 | FH20-migration-store-schema.md | R04, R05 | SQLite tables + `migrations.py` |
| FH21 | FH21-migration-rest-api.md | R04, R05, R22 | `POST/GET /v1/migrations` |
| FH22 | FH22-data-bundle-upload.md | R05, R13 | `PUT …/data-bundle`; profile `migration_bundle` |
| FH23 | FH23-bundle-manifest-spec.md | R13, R14, R19 | Manifest: corpus, raw/sec, broker, wiki |
| FH24 | FH24-migration-progress-api.md | R22 | Step states, bytes, test output on GET |
| FH25 | FH25-job-seed-corpus-volume.md | R05 | Job copies bundle → named volume |
| FH26 | FH26-job-sqlite-to-postgres.md | R03, R05, R21 | Migration job + market migrate tool |
| FH27 | FH27-job-register-edge-route.md | R24 | Caddy snippet + reload via runner |
| FH28 | FH28-gw2-closeout.md | R17 | OpenAPI migration paths; API-only runbook |

---

## GW-3 — forge-market Postgres + container

Sub-program: `forge-market/docs/prompts/fm-postgres-hosting-pdca/` (FMH01–FMH08 ↔ FH30–FH38).

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FH30 / FMH01 | FMH01-connection-factory.md | R03 | `db/connection.py`; wire `studio_server.py` |
| FH31 / FMH02 | FMH02-postgres-ddl.md | R03 | Port `_SCHEMA` to Postgres; Alembic v1 |
| FH32 / FMH03 | FMH03-cli-runner-wiring.md | R03 | CLI/schedulers use factory |
| FH33 / FMH04 | FMH04-migrate-sqlite-to-postgres.md | R03, R05 | `tools/migrate_sqlite_to_postgres.py` |
| FH34 / FMH05 | FMH05-dockerfile-container-contract.md | R02, R15 | Dockerfile, bearer required |
| FH35 / FMH06 | FMH06-secondary-stores-adr.md | R14 | broker.db + wiki.db volume strategy |
| FH36 / FMH07 | FMH07-postgres-tests.md | R03 | `pytest -k postgres`; container smoke |
| FH37 / FMH08 | FMH08-edge-sync-adr.md | R20 | CDP/IBKR split ADR |
| FH38 | FH38-gw3-closeout.md | R18 | FM-ENT-004 → implemented; handbook |

---

## GW-4 — forge-studio-shell

Sub-program: `forge-studio-shell/docs/prompts/fss-studio-shell-pdca/`

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FH40 / FSS01 | FSS01-createStudioApp-core.md | R11 | Config-driven main process |
| FH41 / FSS02 | FSS02-profiles-simple-attach.md | R11 | `simple` + `attach-or-spawn` profiles |
| FH42 / FSS03 | FSS03-preload-ipc-tiers.md | R11 | Tier-1/2 preload APIs |
| FH43 / FSS04 | FSS04-schema-and-examples.md | R11 | `studio.config.schema.json` |
| FH44 / FSS05 | FSS05-npm-publish.md | R11 | `@autowww/forge-studio-shell` package |
| FH45 | FH45-market-adopts-shell.md | R11 | forge-market `desktop/` → manifest |
| FH46 / FSS06 | FSS06-shell-regression.md | R11 | Electron smoke both profiles |
| FH47 | FH47-migrator-adopts-shell.md | R10 | forge-migrator uses same package |
| FH48 | FH48-gw4-closeout.md | — | GW-4 gate |

---

## GW-5 — forge-migrator wizard

Sub-program: `forge-migrator/docs/prompts/fmigr-wizard-pdca/`

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FH50 / FMI01 | FMI01-migrator-scaffold.md | R10 | UI + server + health |
| FH51 / FMI02 | FMI02-recipe-schema-engine.md | R07 | YAML schema; DAG validation |
| FH52 / FMI03 | FMI03-fleet-client.md | R04, R05 | Bearer client for migrations |
| FH53 / FMI04 | FMI04-progress-and-logs-ui.md | R09 | Step states, live logs |
| FH54 / FMI05 | FMI05-test-results-ui.md | R09 | pytest/playwright/curl JSON panel |
| FH55 / FMI06 | FMI06-cursor-sdk-integration.md | R08 | Agent panel; allowlist/denylist |
| FH56 / FMI07 | FMI07-forge-market-recipe.md | R07, R08 | Full recipe local → fleet → verify |
| FH57 / FMI08 | FMI08-generic-recipe-fixture.md | R07 | Second recipe proves agnostic engine |
| FH58 / FMI09 | FMI09-migrator-e2e-playwright.md | R09 | UI drives recipe vs mock Fleet |
| FH59 | FH59-gw5-closeout.md | — | GW-5 gate |

---

## GW-6 — Granite cutover + program closeout

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FH60 | FH60-fleet-upgrade-granite.md | R06 | `update-fleet.sh --remote-git-self-update`; SSH fallback doc |
| FH61 | FH61-staging-migration-dry-run.md | R04, R05 | Migrator vs staging Fleet; no SSH data ops |
| FH62 | FH62-production-cutover.md | R04, R05, R24 | Full recipe on production backup |
| FH63 | FH63-rollback-drill.md | R21 | Stop service + restore bundle via API |
| FH64 | FH64-handbooks-and-openapi.md | R17, R18 | Fleet + Market + Migrator docs |
| FH65 | FH65-granite-boundary-audit.md | R06 | `check-granite-boundary.sh` on all runbooks |
| FH70 | FH70-program-closeout.md | R01–R24 | Final gate; requirements trace matrix green |

---

## Wave 0–6 R01–R24 registry (must appear in requirements ledger)

See [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md).

---

## Orchestration

Gate runner:

```bash
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh <FH00|…|FH70|GW-0|…|GW-6|all>
./scripts/ff-granite-hosting-pdca/check-granite-boundary.sh
```

```bash
cd forge-fleet
./scripts/ff-granite-hosting-pdca/pdca-run-phase.sh FH00 print
./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FH00
./scripts/ff-granite-hosting-pdca/run-wave.sh GW-0
```

Do not open **FH(n+1)** until `./scripts/ff-granite-hosting-pdca/check-phase-gate.sh FHn` is green (respect wave numbering gaps).
