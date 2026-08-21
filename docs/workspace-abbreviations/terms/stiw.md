---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "stiw — Forge STI handbook shell"
description: "Private handbook deploy for STI — forge-sti submodule + kitchensink → Firebase forge-sti-handbook.
"
term_abbr: "stiw"
term_category: "handbook_shell"
---

# stiw — Forge STI handbook shell

Private handbook deploy for STI — forge-sti submodule + kitchensink → Firebase forge-sti-handbook.


## What it is

forge-sti-website/ with generator/build-site.py per forge-sti-handbook rule.

## When people say this

When syncing forge-sti docs into the handbook submodule and deploying sti.forgesdlc.com content.

## Where it lives

forge-sti-website/

## How it fits the ecosystem

Markdown source in sti repo; stiw holds deploy wiring and Firebase config.

## Typical usage in plans and chat

Handbook sync: edit forge-sti/docs, bump stiw submodule, build, deploy --only forge-sti-website.

## Related terms

- [**sti**](sti.md)
- [**ks**](ks.md)

## Disambiguation bridges

- [handbook-deploy-pairs](../bridges/handbook-deploy-pairs.md)

---

*Term page — canonical catalog entry `stiw`.*
