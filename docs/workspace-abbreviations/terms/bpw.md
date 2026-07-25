---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "bpw — Blueprints handbook site"
description: "Public static handbook generator for blueprints.forgesdlc.com — consumes bp and ks submodules.
"
term_abbr: "bpw"
term_category: "handbook_shell"
---

# bpw — Blueprints handbook site

Public static handbook generator for blueprints.forgesdlc.com — consumes bp and ks submodules.


## What it is

Python generator (build-handbook.py, inject-portal-nav.py) emitting website/ for
Firebase project forge-sdlc-blueprints.

## When people say this

When deploying the public handbook, fixing portal nav, or linking process pages from forge knowledge.

## Where it lives

blueprints-website/

## How it fits the ecosystem

Submodule consumer of bp + ks. Sibling to forge (forgesdlc product site). Part of default deploy-websites.sh.

## Typical usage in plans and chat

Dual-wiki plans often list bp (content) and bpw (published HTML) as separate commit targets.

## Do not confuse with

forge

## Related terms

- [**bp**](bp.md)
- [**ks**](ks.md)
- [**fa**](fa.md)

## Disambiguation bridges

- [ks-consumer-chain](../bridges/ks-consumer-chain.md)

---

*Term page — canonical catalog entry `bpw`.*
