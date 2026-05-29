# Admin static assets

Served under `/admin/static/` via FleetHandler.

## Admin app JavaScript

Part **2** of the admin IIFE lives in **`app-src/part2/*.js`** (loaded by `admin.html`). Other parts remain `app-part1.js` and `app-part3.js` … `app-part6.js`.

Edit fragments under `app-src/part2/`, not the stub `app-part2.js`.

Optional: collapse everything back into six parts for a single-file deploy:

```bash
python3 scripts/bundle_admin_app.py
```

(then point `admin.html` at `app-part2.js` instead of the fragment list).

Footprint scans should use **`app-src/part2/`** as the source of truth for the former monolithic part 2.
