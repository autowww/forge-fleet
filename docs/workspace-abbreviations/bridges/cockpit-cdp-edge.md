---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "Cockpit + CDP + Edge + OWA stack"
description: "Cockpit (fccw) orchestrates M365 harvest using lcdl OWA atoms, cdp manager session leases,
and Microsoft Edge CDP attach — not generic Chrome-only automation.
"
term_category: bridge
---

# Cockpit + CDP + Edge + OWA stack

Cockpit (fccw) orchestrates M365 harvest using lcdl OWA atoms, cdp manager session leases,
and Microsoft Edge CDP attach — not generic Chrome-only automation.


## The collision

OWA logic duplicated in cockpit connectors, wrong browser (Chrome vs Edge), CDP port collisions
with A11y Studio, or M365 sync attempted without Edge/Playwright path.

## How to choose

1) New OWA/Teams read behavior? → extend lcdl task + contract; cockpit bridge wires run_task only.
2) Session lease / attach owner? → cdp (FORGE_CDP_MANAGER_URL, typically :18770).
3) Operator browser? → Edge with CDP; COCKPIT_EDGE_FOCUS_EDGE for focus emulation per lcdl docs.
4) EML on disk / manifest upgrades? → cockpit eml_paths + cockpit_data_manifest (not lcdl layout).
5) Start cockpit? → Electron via start-cockpit.sh COCKPIT_PORT=9775 — not browser unless asked.

## Using several at once

lcdl: playwright atoms. cdp: leases. cockpit: SQLite, UI, manifest. OWA/EML: mail path.
fa-acc-leo may share cdp manager — coordinate surface ids. Fleet memory via fccmem optional pulse path.

## Terms covered

- [**cockpit**](../terms/cockpit.md)
- [**fccw**](../terms/fccw.md)
- [**cdp**](../terms/cdp.md)
- [**lcdl**](../terms/lcdl.md)
- [**OWA**](../terms/owa.md)
- [**EML**](../terms/eml.md)
- [**fa-acc-leo**](../terms/fa-acc-leo.md)
- [**fccmem**](../terms/fccmem.md)

## Examples from chat / plan.md

Outlook search-day stall → outlook-mail-preflight via cdp manager with COCKPIT_SYNC_RUN_ID bound session_id.

User: "start cockpit" → ./scripts/start-cockpit.sh background Electron; M365 sync remains Edge unless CDP remote attach configured.

---

*Bridge page `cockpit-cdp-edge` — read when multiple abbreviations appear in one sentence.*
