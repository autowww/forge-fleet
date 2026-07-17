---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "bp — Blueprints"
description: "Reusable SDLC/PDLC process framework and discipline bridges — the methodology
source of truth consumed as a read-only submodule in product repos.
"
term_abbr: "bp"
term_category: "repo"
---

# bp — Blueprints

Reusable SDLC/PDLC process framework and discipline bridges — the methodology
source of truth consumed as a read-only submodule in product repos.


## What it is

Standalone git repo at blueprints/ (autowww/blueprints). Holds SDLC.md, PDLC.md,
Forge methodology, Versona templates, ceremony maps, and per-discipline bridges.

## When people say this

When editing process docs, syncing Cursor rules from bp templates, or bumping
the blueprints submodule pointer in a consumer.

## Where it lives

blueprints/

## How it fits the ecosystem

Feeds bpw and forge as content source; embedded as */blueprints/ submodule in
fl, ff, cyn, forge, bpw, a11y, and cockpit-family repos. Never edit submodule copies.

## Typical usage in plans and chat

Reference bp for DoD/DoR templates, PDCA loops, Versona contracts, and bridge filenames
like BA-SDLC-PDLC-BRIDGE.md.

## Related terms

- [**bpw**](bpw.md)
- [**forge**](forge.md)
- [**ks**](ks.md)

## Disambiguation bridges

- [ks-consumer-chain](../bridges/ks-consumer-chain.md)

---

*Term page — canonical catalog entry `bp`.*
