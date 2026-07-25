---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "flsw — Forge Lenses handbook shell"
description: "Private Firebase deploy shell for the Lenses handbook — submodules forge-lenses + kitchensink.
"
term_abbr: "flsw"
term_category: "handbook_shell"
---

# flsw — Forge Lenses handbook shell

Private Firebase deploy shell for the Lenses handbook — submodules forge-lenses + kitchensink.


## What it is

forge-lenses-website/ builds from forge-lenses/ Markdown via generator/build-site.py.

## When people say this

When deploying lenses-d0fdb or bumping forge-lenses submodule in the website repo.

## Where it lives

forge-lenses-website/

## How it fits the ecosystem

Product Markdown in fl; pointer bump + build in flsw. deploy-websites.sh --only forge-lenses-website.

## Typical usage in plans and chat

Edit docs in fl, deploy from flsw — never treat flsw as the product source tree.

## Do not confuse with

fl

## Related terms

- [**fl**](fl.md)
- [**ks**](ks.md)

## Disambiguation bridges

- [handbook-deploy-pairs](../bridges/handbook-deploy-pairs.md)

---

*Term page — canonical catalog entry `flsw`.*
