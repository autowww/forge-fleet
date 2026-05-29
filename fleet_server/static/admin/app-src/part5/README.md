# Admin app — part 5 fragments (jobs, services, container config, git update)

Semantic modules merged into the admin IIFE after part 4 (KPI tile animations) and before part 6 (snapshot polling and event wiring). Listed in `MANIFEST.txt`.

| File | Responsibility |
|------|----------------|
| `kpi-tile-anims-close.js` | Closing `}` for `applyKpiTileAnims` (body in part 4) |
| `job-display-helpers.js` | `statusPill`, `jobOutcomeHuman`, `fleetJobArgvShell` |
| `job-detail.js` | `renderFleetJobDetailPayload`, `openFleetJobDetail` |
| `auth-errors.js` | `authHeaders`, `setErr` |
| `managed-services-render.js` | `renderManagedServices` — forge_llm compose stacks table |
| `container-config-state.js` | Module state for types/templates editors |
| `requirement-templates.js` | `renderFleetReqTemplatesTable`, `loadRequirementTemplatesOnce` |
| `container-type-modal.js` | `openFleetTypeModal` |
| `requirement-template-modal.js` | `openFleetReqTemplateModal` |
| `container-types-load.js` | `loadContainerTypesOnce` |
| `self-update-ui.js` | `fleetUpdateUiRefresh`, `applySelfUpdateMeta`, `showSystemUpdateModal` |
| `self-update-run.js` | `formatSelfUpdateSteps`, `waitFleetBack`, `doGitSelfUpdate` |
| `git-remote-check.js` | `gitShaPrefix7`, `checkRemoteAgainstGitHub` |
| `jobs-pager.js` | `renderFleetJobsPager` |

Shared closure from earlier parts: `esc`, `fmtTime`, `LS`, `errEl`, `refreshContainerTypesTelemetry`, `__fleetLastOrchestration`, `FLEET_GITHUB_REPO`, `__fleetSelfUpdateConfigured`, `fleetJobsPageSize`, `fleetJobsOffset`.
