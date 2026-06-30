---
title: Forge CDP Manager
summary: Cross-process Edge CDP surface leases for shared Edge profiles
nav_order: 10
audience: operator
---

# Forge CDP Manager

Install this **Fleet App** to inspect and reclaim **CDP surface leases** when Cockpit, Knowledge Assistant, and CLI harnesses share one operator Edge profile (`:9222`, `:9223`, …).

## What you get

- A **CDP Manager** tab in Fleet `/admin/` with live lease table and stale reclaim action.
- **In-package docs** mirrored at `/admin/apps/forge-cdp-manager/docs/` on your Fleet host.

## Trust boundary

- Handlers read lease files under `~/.cache/forge-cdp/leases` (or `FORGE_CDP_MANAGER_LOCK_DIR`).
- Fleet does not start Edge or attach Playwright; it only surfaces lease metadata and reclaim helpers.
- This package does not replace Cockpit HTTP routes on port 9775.

## Prerequisites

- Fleet with FAEP v1 (`POST /v1/fleet-apps/install`).
- `pip install` target includes `forge-cdp-manager` wheel from the package zip.

## Install from Fleet admin

1. Open **`/admin/`** → **Apps** tab.
2. Click **Install** next to **Forge CDP Manager**.
3. Open the **Forge CDP Manager** tab to view leases.

## See also

- Upstream repo: [forge-cdp-manager](https://github.com/autowww/forge-cdp-manager)
- Protocol: [Fleet Apps](../build-201/03-fleet-apps-protocol.md)
