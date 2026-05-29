# Admin static assets

Served under `/admin/static/` via FleetHandler.

## Admin HTML shell

Markup lives in **`html_src/`** (fragments + `MANIFEST.txt`). **`GET /admin/`** assembles the page at runtime via **`fleet_server.admin_shell`**. The repo-root **`static/admin.html`** is a short stub for footprint scans; optional full bundle: **`python3 scripts/bundle_admin_html.py`**.

## Admin app JavaScript

Parts **2**, **3**, **4**, and **5** of the admin IIFE live in **`app-src/part2/*.js`**, **`app-src/part3/*.js`**, **`app-src/part4/*.js`**, and **`app-src/part5/*.js`** (loaded by `admin.html`). Other parts remain `app-part1.js` and `app-part6.js`.

Edit fragments under `app-src/part2/`, `app-src/part3/`, `app-src/part4/`, and `app-src/part5/`, not the stub `app-part2.js`, `app-part3.js`, `app-part4.js`, or `app-part5.js`.

Optional: collapse everything back into six parts for a single-file deploy:

```bash
python3 scripts/bundle_admin_app.py
```

(then point `admin.html` at `app-part2.js` instead of the fragment list).

Footprint scans should use **`html_src/`**, **`app-src/part2/`**, **`app-src/part3/`**, **`app-src/part4/`**, and **`app-src/part5/`** as source of truth for admin markup and the former monolithic JS parts 2–5.
