# Examples — Lenses / Studio integration

Checklist:

| Step | Detail |
|------|--------|
| Studio env | **`LENSES_FLEET_URL`** + **`LENSES_FLEET_TOKEN`** (**Settings → Fleet**) |
| Evidence | **`POST /v1/admin/test-fleet`** only via workspace server (**never raw browser**) |
| Proof | Matching rows under **`/admin/` Recent jobs** + **`meta.sqlite_path`** consistency |

Deep narrative → **[Learn 101 — Admin & Studio](../learn-101/07-admin-dashboard-and-studio.md)**.

## Purpose

Checklist for wiring Forge Lenses / Studio to Fleet (**`LENSES_FLEET_*`**) and validating via **`test-fleet`**.

## Prerequisites

Studio build that supports Fleet settings; workspace server reachable.

## Copy-paste steps

Configure env in Studio, run **`POST /v1/admin/test-fleet`** from the workspace context (not ad-hoc browser **`fetch`** without token handling).

## Expected output

**`/admin/`** recent jobs list aligns with **`meta.sqlite_path`** on the Fleet host.

## Error handling

Treat **401** as token/binding mismatch; re-check **`LENSES_FLEET_URL`** (no stray slash) and firewall rules.

## Security notes

Never expose admin tokens to untrusted browser extensions; use Studio-managed storage.

## Related

- **[Learn 101 — Admin & Studio](../learn-101/07-admin-dashboard-and-studio.md)**
- **[HTTP API](../reference/01-http-api-reference.md)** (**`postAdminTestFleet`**)

## Validation status

- OpenAPI includes admin routes in **[`../schemas/openapi.json`](../schemas/openapi.json)**; Lenses docs cross-checked by **`check-docs-links.py`**.
