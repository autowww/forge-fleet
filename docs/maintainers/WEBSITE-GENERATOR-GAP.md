# Website generator — handbook build notes

The public handbook at **https://fleet.forgesdlc.com/** is built from the **`forge-fleet-website`** repository, which embeds **`forge-fleet`** as a **git submodule** under **`forge-fleet/`**.

## Navigation and IA

Horizontal IA and section sidebars are driven by **`docs/site-nav.yaml`** in **forge-fleet** (loaded when `HandbookBuildConfig.site_nav_yaml` is set in **`forge-fleet-website/generator/build-site.py`**). Page order within a section still follows the Markdown tree and optional frontmatter (`nav_order`, `hide_from_nav`).

Legacy note: there is no Forge Lenses–style `nav.yml` unless you opt into one; changing top-level buckets means editing **`site-nav.yaml`** and rebuilding.

## Local preview (two-checkouts)

After editing **`forge-fleet/docs/`**, point the website submodule at your branch (or rsync docs into **`forge-fleet-website/forge-fleet/docs/`**), then:

```bash
cd forge-fleet-website
python3 generator/build-site.py
python3 scripts/check-site-smoke.py
python3 scripts/check-site-ux.py
```

## Publishing

Commit the **forge-fleet** submodule pointer (and any tracked **`website/`** output) in **`forge-fleet-website`** per that repo’s workflow. **`sync-kitchensink-and-rebuild.sh`** / **`deploy-websites.sh`** at the workspace root are the broader propagation entry points when multiple sites move together.
