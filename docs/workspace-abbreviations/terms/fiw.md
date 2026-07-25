---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "fiw — Forge Intelligence handbook shell"
description: "Private handbook deploy for Intelligence — forge-intelligence submodule + kitchensink → forge-intelligence-handbook (intelligence.forgesdlc.com).
"
term_abbr: "fiw"
term_category: "handbook_shell"
---

# fiw — Forge Intelligence handbook shell

Private handbook deploy for Intelligence — forge-intelligence submodule + kitchensink → forge-intelligence-handbook (intelligence.forgesdlc.com).


## What it is

forge-intelligence-website/ with generator/build-site.py per forge-intelligence-handbook rule.

## When people say this

When syncing forge-intelligence docs into the handbook submodule and deploying fiw.

## Where it lives

forge-intelligence-website/

## How it fits the ecosystem

Markdown source in fi repo; fiw holds deploy wiring and Firebase config. Custom domain intelligence.forgesdlc.com.

## Typical usage in plans and chat

Handbook sync: edit forge-intelligence/docs, bump fiw submodule, build, deploy --only forge-intelligence-website.

## Related terms

- [**fi**](fi.md)
- [**ks**](ks.md)

## Disambiguation bridges

- [handbook-deploy-pairs](../bridges/handbook-deploy-pairs.md)

---

*Term page — canonical catalog entry `fiw`.*
