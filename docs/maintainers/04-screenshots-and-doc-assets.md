# Maintainers — Screenshots and doc assets

> **Maintainer-facing:** screenshot automation targets disposable ports and may churn with Playwright upgrades.

Doc PNGs live in **`docs/assets/`**. The **forge-fleet-website** build copies them into **`website/assets/`** so image Markdown can use repo-relative paths such as **`../assets/admin-overview.png`** from nested handbook folders (match the path depth of the `.md` file you are editing).

Authoritative workflow text remains in **`[docs/assets/README.md](../assets/README.md)`**; update that file when Playwright commands or baselines change.
