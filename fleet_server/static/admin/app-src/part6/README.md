# Admin app — part 6 fragments (snapshot poll, events, boot)

Semantic modules merged into the admin IIFE after part 5 (jobs pager) and closing the shared IIFE. Listed in `MANIFEST.txt`.

| File | Responsibility |
|------|----------------|
| `snapshot-fetch.js` | `fetchAdminSnapshot` — GET `/v1/admin/snapshot` with auth and error handling |
| `snapshot-apply.js` | `applySnapshotData` — version line, integrations, charts, tiles, jobs table |
| `snapshot-load.js` | `loadSnapshot` — fetch then apply |
| `poll-scheduler.js` | `scheduleNext`, `tick` — poll timer driven by `POLL_MS` |
| `forge-service-post.js` | `forgeSvcPost` — POST start/stop for managed compose services |
| `click-delegation-jobs.js` | Click: job detail modal, jobs table pagination |
| `click-delegation-services.js` | Click: managed service start/stop |
| `click-delegation-container-config.js` | Click: container types, requirement templates, template build |
| `click-delegation-admin.js` | Click: git self-update, power diagnostics modal |
| `form-add-service.js` | Submit: register new `forge_llm` container service |
| `form-type-save.js` | Click: save container type modal (POST/PUT) |
| `form-req-template-save.js` | Click: save requirement template row in editor |
| `chart-y-preference.js` | Chart Y-axis linear/log toggle + `localStorage` |
| `ui-refresh-handlers.js` | Refresh buttons, telemetry history open, tab chart repaint, copy install cmd |
| `boot-close.js` | `visibilitychange`, a11y modal stub fill, poll interval, initial load, IIFE close |

Shared closure from earlier parts: `authHeaders`, `setErr`, `esc`, `fmtTime`, `POLL_MS`, `fleetJobsPageSize`, `fleetJobsOffset`, chart/orchestration helpers, container-config modals from part 5.
