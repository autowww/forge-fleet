---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "cdp — forge-cdp-manager"
description: "CDP control plane — surface leases, browser session registry, HTTP API for attach owners (typical :18770).
"
term_abbr: "cdp"
term_category: "repo"
---

# cdp — forge-cdp-manager

CDP control plane — surface leases, browser session registry, HTTP API for attach owners (typical :18770).


## What it is

forge-cdp-manager/ exposes FORGE_CDP_MANAGER_URL sessions. Cockpit and A11y Studio attach via CDP.

## When people say this

When debugging browser attach, surface leases, outlook-mail CDP manager, or strangler migrations.

## Where it lives

forge-cdp-manager/

## How it fits the ecosystem

Protocol CDP (Chrome DevTools Protocol) implemented here as a managed service. Edge for M365 harvest.

## Typical usage in plans and chat

Plans crossing cockpit + browser automation should list cdp manager URL and single-attach-owner invariant.

## Do not confuse with

CDP

## Related terms

- [**cockpit**](cockpit.md)
- [**fa-acc-leo**](fa-acc-leo.md)
- [**lcdl**](lcdl.md)

## Disambiguation bridges

- [cockpit-cdp-edge](../bridges/cockpit-cdp-edge.md)

---

*Term page — canonical catalog entry `cdp`.*
