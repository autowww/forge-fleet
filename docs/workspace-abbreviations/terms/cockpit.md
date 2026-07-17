---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "cockpit — Forge Cockpit (web)"
description: "M365/Teams ingest dashboard — Electron studio + Python cockpit_server; primary laptop runner.
"
term_abbr: "cockpit"
term_category: "repo"
---

# cockpit — Forge Cockpit (web)

M365/Teams ingest dashboard — Electron studio + Python cockpit_server; primary laptop runner.


## What it is

forge-cockpit-web/ (autowww/forge-cockpit-web). Start via ./scripts/start-cockpit.sh;
COCKPIT_PORT=9775 default. Alias fccw.

## When people say this

When user says start cockpit, launch cockpit, or cockpit studio — Electron shell, not browser-only unless asked.

## Where it lives

forge-cockpit-web/

## How it fits the ecosystem

Siblings: fccm (mobile), fccmem (Fleet memory client). Uses lcdl, cdp, Edge/OWA for ingest.

## Typical usage in plans and chat

Cockpit plans should name lcdl boundary, CDP manager URL, and M365 sync (Edge/Playwright) explicitly.

## Do not confuse with

fccm
fccmem
cdp

## Related terms

- [**fccm**](fccm.md)
- [**fccmem**](fccmem.md)
- [**lcdl**](lcdl.md)
- [**cdp**](cdp.md)
- [**ff**](ff.md)

## Disambiguation bridges

- [cockpit-cdp-edge](../bridges/cockpit-cdp-edge.md)

---

*Term page — canonical catalog entry `cockpit`.*
