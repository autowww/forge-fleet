# Granite hosting — requirements ledger

All requirements for the `ff-granite-hosting-pdca` program (FH00–FH70). Map each to gate evidence before implementing.

| ID | Requirement | Deliverable | PDCA phase(s) | Gate evidence |
|----|-------------|-------------|---------------|---------------|
| R01 | Extend Fleet container architecture for long-lived apps | `managed_compose_service.py`, `forge_market_studio` type | FH10–FH14 | `check-phase-gate.sh FH14` |
| R02 | Host Market Studio on Granite Fleet | `deploy/forge-market-studio/compose.yaml` + service record | FH15–FH18 | compose status API green |
| R03 | PostgreSQL instead of SQLite (`market.db`) | Connection factory, DDL, migrate tool | FH30–FH35 | `pytest -k postgres` |
| R04 | Deployment solely through Fleet API | Container-service + migration deploy steps | FH20–FH28, FH60 | no SSH deploy in runbook |
| R05 | Data transfer solely through Fleet API | `/v1/migrations/{id}/data-bundle` + seed jobs | FH20–FH25 | upload bytes == local backup |
| R06 | Granite SSH only for Fleet version update | Boundary doc + runbook lint gate | FH01, FH60, FH65 | `check-granite-boundary.sh` |
| R07 | Application-agnostic migration wizard | Recipe schema + engine in forge-migrator | FH50–FH54 | second dummy recipe runs |
| R08 | Cursor AI modernization in sequence | `integrations/cursor/` + migrator UI agent panel | FH55–FH56 | agent step produces diff + tests |
| R09 | Tests + progress shown in migrator UI | Step state machine, log/test panels | FH57–FH58 | Playwright migrator e2e |
| R10 | Private `forge-migrator` Electron repo | `autowww/forge-migrator` | FH03, FH04, FH50 | repo exists + private |
| R11 | Private generic Electron studio shell repo | `autowww/forge-studio-shell` | FH02, FH40 | npm package + schema |
| R12 | Private `forge-market` GitHub repo | visibility + integration branch | FH03 | `gh repo view` private |
| R13 | Corpus + raw SEC + config in migration bundle | Extended backup manifest in migration API | FH23 | inventory bytes parity |
| R14 | `broker.db` + wiki workspaces policy | v1 file volumes on compose; bundle flags | FH35, FH23 | ADR + mount paths |
| R15 | Cloud auth required | `FORGE_MARKET_STUDIO_API_TOKEN` enforced in container profile | FH36 | unauthenticated `/api/*` → 401 |
| R16 | `forge_llm` regression | Generalize without breaking LLM gateway | FH14, FH70 | existing LLM start/stop tests |
| R17 | OpenAPI + Fleet handbook | `docs/build-201/08-*`, openapi.json | FH18, FH28 | handbook build |
| R18 | Market handbook dual-wiki | system/operator market-studio pages | FH38, FH70 | feature-index FM-ENT-004 → implemented |
| R19 | FM-ENT-008 backup extended | Include broker/raw-sec options in bundle spec | FH23 | manifest documents fields |
| R20 | Edge integrations (CDP/IBKR) documented | Split architecture ADR; cloud read path | FH37 | handbook limits section |
| R21 | Rollback via Fleet API | `restore_from_bundle` migration job | FH26 | rollback e2e in staging |
| R22 | Cost/ops visibility | Migration session exposes bytes transferred | FH24 | GET migration totals |
| R23 | Image delivery without SSH | Fleet job build or registry pull in rollout API | FH17 | image id in service status |
| R24 | Caddy/edge route without SSH | `register_edge_route` fleet migration step | FH27 | HTTPS probe via migrator |

**Assumptions:** Postgres Compose sidecar on Granite; repos under **autowww**; Electron stays local operator shell; browser path to Fleet-routed HTTPS for hosted Studio. One phase per commit; gate before next phase.
