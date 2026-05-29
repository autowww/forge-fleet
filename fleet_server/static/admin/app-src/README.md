# Admin app JavaScript sources

The operator UI boot script is one shared IIFE split across `app-part1.js` … `app-part6.js` for HTTP caching. Those files are **generated**; edit fragments here and run the bundle.

## Bundle

From the forge-fleet repo root:

```bash
python3 scripts/bundle_admin_app.py
```

Writes `fleet_server/static/admin/app-part*.js` as valid JavaScript (concatenates fragments, then splits at line boundaries). The shipped **admin.html** loads `app-src/part2/*.js` and `app-src/part4/*.js` directly so `app-part2.js` / `app-part4.js` stay small pointers; use the bundle when you need single-file parts again.

## Layout

| Path | Role |
|------|------|
| `part2/` | Host metrics, overview tiles, inline chart series helpers (former `app-part2.js`) |
| `part2/MANIFEST.txt` | Fragment order for the part-2 region |
| `part4/` | Orchestration UI, overview tile row, telemetry history fetch (former `app-part4.js`) |
| `part4/MANIFEST.txt` | Fragment order for the part-4 region |

Do not hand-edit `app-part*.js` except via the bundle after changing fragments. Footprint scans should treat **`app-src/part2/`** and **`app-src/part4/`** as source of truth for those regions.
