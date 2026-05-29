# Admin app — part 3 fragments (telemetry charts & overview tiles)

Semantic modules merged into the admin IIFE between part 2 (host metrics / chart helpers) and part 4 (orchestration UI). Listed in `MANIFEST.txt`.

| File | Responsibility |
|------|----------------|
| `telemetry-x-axis.js` | `fleetTelemetryXAxisMarkup` — UTC time ticks under modal history charts |
| `telemetry-grid-paths.js` | `fleetTelemetryGridAndPaths` — grid lines and CPU/RAM/temp/load/disk SVG paths |
| `telemetry-samples-markup.js` | `samplesToMetricRows`, `renderTelemetrySvgMarkup` |
| `telemetry-chart-refresh.js` | `refreshTelemetryChartsFromDb`, `appendLiveTelemetryTail` — `/v1/telemetry` poll + live tail |
| `power-ledger-format.js` | `fmtWatts`, `formatLedgerKwhLine`, `formatLedgerKwhShort` |
| `power-overview-tile.js` | `renderPowerTile`, `__fleetLastPowerTotalW` |
| `thermal-overview-tile.js` | `renderThermalTile` |
| `fleet-chart-render.js` | `renderFleetChart`, `renderTelemetryChartInto` |
| `telemetry-history-modal-open.js` | Start of `openFleetTelemetryHistoryModal` (body continues in `app-src/part4/telemetry-history-fetch.js`) |

Shared closure from earlier parts: `esc`, `authHeaders`, `chartBuf`, `orchBuf`, `CHART_MS`, part-2 chart helpers (`chartPctToY`, `hostMetricsForChart`, `buildModalChartRows`, …), part-2 tiles (`tileMark`, `MARK_*`, `__fleetRaplPrev`, `fleetPowerWAnim`).
