# Maintainer — Docs release checklist

Use before publishing **forge-fleet** + **forge-fleet-website** or cutting a semver that markets doc changes.

1. **Pull & branch**
   - `git pull --rebase` on **`forge-fleet`** + consumer **`forge-fleet-website`**.
2. **Route / OpenAPI parity**
   - `python3 scripts/check-docs-contracts.py`
3. **JSON syntax**
   - `python3 scripts/check-docs-json.py`
4. **Internal Markdown links**
   - `python3 scripts/check-docs-links.py`
5. **Examples spot-check**
   - Skim **`docs/examples/`** + **`docs/build-201/05-examples-and-recipes.md`** for stale route names.
6. **Handbook build**
   - From **`forge-fleet-website`**: `python3 generator/build-site.py`
   - Confirm page count stable; delete stale **`website/*.html`** if generator leaves orphans.
7. **SEO / Hosting smoke (post-deploy)**
   - Load `https://fleet.forgesdlc.com/index.html` + random **Learn/Begin** page, confirm canonical tag present.
8. **UX smoke (static build)**
   - From **`forge-fleet-website`**: `python3 scripts/check-site-smoke.py`
   - `python3 scripts/check-site-ux.py` — horizontal nav present, single `<main id="main">`, breadcrumb landmark, no duplicate `README.md` family rail bug (see forge-autodoc `lenses_split_family_pages` directory scope).
9. **IA manifest**
   - If you changed handbook sections, update **`docs/site-nav.yaml`** in **forge-fleet** and rebuild; confirm **More** dropdown lists Maintainers / Design / Changelog only (no mega-menu of all chapters).
10. **Tagging / comms**
   - Mention doc-affecting commits in **`CHANGELOG.md`** (`### Host operator` when needed).
