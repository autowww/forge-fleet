# Admin app JavaScript sources

The operator UI boot script is one shared IIFE split across `app-part1.js` … `app-part6.js` for HTTP caching. Those files are **generated**; edit fragments here and run the bundle.

## Bundle

From the forge-fleet repo root:

```bash
python3 scripts/bundle_admin_app.py
```

Writes `fleet_server/static/admin/app-part*.js` as valid JavaScript (concatenates fragments, then splits at line boundaries). The shipped **admin.html** loads `app-src/part2/*.js` … `app-src/part6/*.js` directly so `app-part2.js` … `app-part6.js` stay small pointers; use the bundle when you need single-file parts again.

## Layout

| Path | Role |
|------|------|
| `part2/` | Host metrics, overview tiles, inline chart series helpers (former `app-part2.js`) |
| `part2/MANIFEST.txt` | Fragment order for the part-2 region |
| `part3/` | Telemetry SVG charts, poll refresh, power/thermal overview tiles (former `app-part3.js`) |
| `part3/MANIFEST.txt` | Fragment order for the part-3 region |
| `part4/` | Orchestration UI, overview tile row, telemetry history fetch (former `app-part4.js`) |
| `part4/MANIFEST.txt` | Fragment order for the part-4 region |
| `part5/` | Jobs UI, managed services, container types/templates, git self-update (former `app-part5.js`) |
| `part5/MANIFEST.txt` | Fragment order for the part-5 region |
| `part6/` | Snapshot polling, event wiring, IIFE boot close (former `app-part6.js`) |
| `part6/MANIFEST.txt` | Fragment order for the part-6 region |

Do not hand-edit `app-part*.js` except via the bundle after changing fragments. Footprint scans should treat **`app-src/part2/`** through **`app-src/part6/`** as source of truth for those regions.
