# Admin app — part 4 fragments (orchestration UI & overview tiles)

Semantic modules merged into the admin IIFE between part 3 (telemetry modal SVG) and part 5 (jobs tables). Listed in `MANIFEST.txt`.

| File | Responsibility |
|------|----------------|
| `telemetry-history-fetch.js` | Body of `openFleetTelemetryHistoryModal` (multi-period `/v1/telemetry` fetch) |
| `chart-y-hint.js` | `refreshChartYHint` — chart Y-axis scale caption |
| `orchestration-scalars.js` | `orchestrationScalars` — managed services / running job counts |
| `orchestration-chart.js` | `renderOrchestrationChart` — workload history SVG |
| `orchestration-header.js` | `formatTypeTelemetry`, `refreshContainerTypesTelemetry`, `paintOrchestrationHeader` |
| `cooldown-format.js` | `formatCooldownS` — human-readable throttle wait duration |
| `cooldown-tile.js` | `renderCooldownTile` — LLM thermal throttle overview tile HTML |
| `overview-tiles.js` | `renderTiles` — host KPI tile row (CPU, thermal, RAM, load, disk, power, GPU) |
| `kpi-tile-anims.js` | `applyKpiTileAnims` — snapshot targets for bar/gauge animations |

Shared closure from earlier parts: `esc`, `authHeaders`, `orchBuf`, `renderTelemetryChartInto`, part-2 host/GPU/disk helpers, `renderPowerTile`, `renderThermalTile`, `renderCpuCompactTile`.

`openFleetTelemetryHistoryModal` is declared in part 3; this folder continues its async body. `applyKpiTileAnims` closes in part 5 (leading `}`).
