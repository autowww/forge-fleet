---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "flw — Forge LCDL handbook shell"
description: "Private handbook deploy for LCDL — forge-lcdl submodule + kitchensink → Firebase lcdl-542d8.
"
term_abbr: "flw"
term_category: "handbook_shell"
---

# flw — Forge LCDL handbook shell

Private handbook deploy for LCDL — forge-lcdl submodule + kitchensink → Firebase lcdl-542d8.


## What it is

forge-lcdl-website/ with generator/build-site.py per forge-lcdl-handbook rule.

## When people say this

When syncing forge-lcdl docs into the handbook submodule and deploying lcdl.forgesdlc.com content.

## Where it lives

forge-lcdl-website/

## How it fits the ecosystem

Markdown source in lcdl repo; flw holds deploy wiring and Firebase config.

## Typical usage in plans and chat

Handbook sync: edit forge-lcdl/docs, bump flw submodule, build, deploy --only forge-lcdl-website.

## Related terms

- [**lcdl**](lcdl.md)
- [**ks**](ks.md)

## Disambiguation bridges

- [handbook-deploy-pairs](../bridges/handbook-deploy-pairs.md)
- [lcdl-repo-vs-lcdl-hub](../bridges/lcdl-repo-vs-lcdl-hub.md)

---

*Term page — canonical catalog entry `flw`.*
