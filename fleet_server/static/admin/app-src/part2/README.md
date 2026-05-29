# Admin app — part 2 fragments (host metrics & tiles)

Semantic modules merged into the admin IIFE between part 1 (boot, token, CPU anim) and part 3 (telemetry modal SVG). Listed in `MANIFEST.txt`.

| File | Responsibility |
|------|----------------|
| `cpu-compact-tile.js` | `renderCpuCompactTile` HTML for the CPU overview tile |
| `gpu-metrics.js` | GPU util/VRAM aggregates and vendor device presence |
| `tile-marks.js` | Inline SVG brand marks (`MARK_*`) |
| `rapl-state.js` | RAPL power sampling state (`__fleetRaplPrev`) |
| `gpu-branding.js` | Vendor logo `<img>` helpers |
| `tile-format-load.js` | `tileMark`, load-average formatting, scale denominator |
| `disk-metrics.js` | Disk space/I/O aggregation for the storage tile |
| `trend-samples.js` | Trend buffer push and heat/cool CSS classes |
| `load-metrics.js` | Load average → bar percentages |
| `host-metrics.js` | Thermal max and chart row raw fields |
| `chart-series.js` | Poll chart resampling, SVG paths, time normalization |
| `chart-aggregate.js` | Bucket averaging for modal/history charts |
| `chart-buckets.js` | Nice time bucket picker |
| `modal-chart-rows.js` | `buildModalChartRows` for telemetry modal |

Shared closure from part 1: `esc`, `cpuPct`, `fleetCpuAnim`, `loadZone4`, `LS_*`, `__fleetTrendBuf`, `TREND_MS`, `POLL_MS`.
