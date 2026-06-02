# Admin static assets

Served under `/admin/static/` via FleetHandler.

## Admin HTML shell

Markup lives in **`html_src/`** (fragments + `MANIFEST.txt`). **`GET /admin/`** assembles the page at runtime via **`fleet_server.admin_shell`**. The repo-root **`static/admin.html`** is a short stub for footprint scans; optional full bundle: **`python3 scripts/bundle_admin_html.py`**.

## Admin app JavaScript

Parts **2**–**6** of the admin IIFE live in **`app-src/part2/*.js`** … **`app-src/part6/*.js`**. Part **1** is the head of **`app-part1.js`** (trimmed when bundling).

**Runtime (`GET /admin/`):** loads a single **`app-bundle.js`** (full IIFE). Regenerate after editing fragments:

```bash
python3 scripts/bundle_admin_app.py
```

That also refreshes **`app-part*.js`** line slices for footprint scans. Do not load `app-src` fragments directly in the browser — they are not separate scripts.

Footprint scans should use **`html_src/`** and **`app-src/part2/`** … **`app-src/part6/`** as source of truth for admin markup and the former monolithic JS parts 2–6.
