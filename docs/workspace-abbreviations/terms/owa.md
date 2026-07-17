---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "OWA — Outlook Web App"
description: "Browser Outlook UI harvested via Edge CDP — search-day tier, EML export, DOM list strategies.
"
term_abbr: "OWA"
term_category: "platform"
---

# OWA — Outlook Web App

Browser Outlook UI harvested via Edge CDP — search-day tier, EML export, DOM list strategies.


## What it is

Cockpit outlook ingest paths: COCKPIT_OUTLOOK_OWA_ONLY, sequential catalog, lcdl OWA atoms.

## When people say this

When planning mail ingest without Graph API, unread preserve, or search-day sync loops.

## Where it lives

forge-cockpit-web/docs/; forge-lcdl/docs/playwright/

## How it fits the ecosystem

LCDL owns OWA read atoms; Cockpit owns SQLite wire fields and manifest layout upgrades.

## Typical usage in plans and chat

New OWA behavior → lcdl task first; cockpit bridge only exposes run_task wiring.

## Related terms

- [**EML**](eml.md)
- [**lcdl**](lcdl.md)
- [**cockpit**](cockpit.md)
- [**cdp**](cdp.md)

## Disambiguation bridges

- [cockpit-cdp-edge](../bridges/cockpit-cdp-edge.md)

---

*Term page — canonical catalog entry `owa`.*
