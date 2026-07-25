---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "ff — Forge Fleet"
description: "HTTP bearer orchestrator for Docker-argv jobs — SQLite job store, admin UI, git-self-update endpoint.
"
term_abbr: "ff"
term_category: "repo"
---

# ff — Forge Fleet

HTTP bearer orchestrator for Docker-argv jobs — SQLite job store, admin UI, git-self-update endpoint.


## What it is

forge-fleet/ with /v1/* JSON API, typical user install on port 18766 via update-user.sh.

## When people say this

When shipping fleet releases (update-fleet.sh), running bank-health jobs, or remote git-self-update from cert.

## Where it lives

forge-fleet/

## How it fits the ecosystem

~/forge-fleet is authoritative for "update service" on localhost. Handbook via ffw → fleet-2f1d3.

## Typical usage in plans and chat

Distinguish "update fleet" (release script) from "update service" (local pull + restart).

## Do not confuse with

ffw

## Related terms

- [**ffw**](ffw.md)
- [**cert**](cert.md)
- [**fwc**](fwc.md)
- [**fp**](fp.md)

## Disambiguation bridges

- [handbook-deploy-pairs](../bridges/handbook-deploy-pairs.md)
- [control-plane-stack](../bridges/control-plane-stack.md)

---

*Term page — canonical catalog entry `ff`.*
