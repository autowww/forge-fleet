# Admin static assets

Served under `/admin/static/` via FleetHandler.

## Admin app JavaScript

Parts **2** and **4** of the admin IIFE live in **`app-src/part2/*.js`** and **`app-src/part4/*.js`** (loaded by `admin.html`). Other parts remain `app-part1.js`, `app-part3.js`, `app-part5.js`, and `app-part6.js`.

Edit fragments under `app-src/part2/` and `app-src/part4/`, not the stub `app-part2.js` / `app-part4.js`.

Optional: collapse everything back into six parts for a single-file deploy:

```bash
python3 scripts/bundle_admin_app.py
```

(then point `admin.html` at `app-part2.js` instead of the fragment list).

Footprint scans should use **`app-src/part2/`** and **`app-src/part4/`** as the source of truth for the former monolithic parts 2 and 4.
