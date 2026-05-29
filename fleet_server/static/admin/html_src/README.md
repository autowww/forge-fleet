# Admin HTML shell fragments

Semantic markup for **`GET /admin/`**. The HTTP server concatenates these files in **`MANIFEST.txt`** order via **`fleet_server.admin_shell`**.

## Layout

| Folder | Responsibility |
|--------|----------------|
| `shell/` | Document start (head, theme flash script, CSS links), script tags, closing tags |
| `chrome/` | Fixed UI: theme dropdown, accessibility page-overview trigger |
| `main/` | Page header, tab navigation, tab-content wrapper open/close |
| `tabs/` | Bootstrap tab panes: Overview, Services, Containers, Jobs |
| `modals/` | Bootstrap dialogs (job detail, type edit, telemetry history, …) |

## Edit workflow

1. Change the relevant fragment under this tree (preserve element `id`s — admin JS binds to them).
2. Keep **`MANIFEST.txt`** order aligned with document structure.
3. **`GET /admin/`** serves the assembled page; no rebuild required for normal dev.

Optional single-file bundle (CI or offline preview):

```bash
python3 scripts/bundle_admin_html.py
```

That overwrites **`../admin.html`** with the concatenated shell (~675 lines). Runtime assembly from fragments is the default; the bundled file is optional.

Re-split from a monolithic **`admin.html`** (mechanical):

```bash
python3 scripts/split_admin_html_fragments.py
```

## Footprint

Footprint scans should treat **`html_src/`** as the source of truth for admin markup. The root **`admin.html`** stub is a developer pointer only.
