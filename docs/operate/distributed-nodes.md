# Distributed Fleet nodes (operator map)

**Outcome:** you can name which machine runs jobs, which machine holds Market Postgres, and how a laptop reaches Granite without SSH — using Fleet HTTP and app gateways only.

**Dual-wiki:** edit this `.md` file; rebuild the handbook with `python3 generator/build-site.py` in **forge-fleet-website**.

## What is shipped today

| Layer | Behavior |
|-------|----------|
| **Job execution** | Each Fleet host runs `docker_argv` (and related) jobs **on that host only**. There is no automatic cross-node job forward or placement in production yet. |
| **Federated admin** | A **laptop** Fleet (`127.0.0.1:18766`) can register **remote peers** in `{FLEET_DATA_DIR}/etc/remote-peers.json` and proxy read-only admin calls (`snapshot`, `telemetry`, `jobs`, `capacity`). See [Connect to remote Fleet](../learn-101/08-connect-remote-fleet.md). |
| **Market data plane** | **Granite** (or another public Fleet host) runs managed compose for Market Studio: Postgres + `market-app`. Analyst laptops use **thin client** Market Studio (`:9792`) and relay research `/api/*` through a Fleet **app gateway** (`/v1/app-gateways/{id}/…`). |
| **Environments** | DEV and PROD Market stacks are separate gateways and compose roots — [Fleet environments](environments.md), [Granite Market Studio environments](granite-market-studio-environments.md). |

**Not shipped:** mesh job placement, reservation ledger enforcement, or stateful failover across nodes. Design and future phases live in **ff-fleet-mesh-pdca** ([design index](../design/README.md)); treat that program as roadmap, not current operator steps.

## Topology (typical Forge workspace)

```text
Operator laptop
  ├── forge-fleet-user (:18766)     jobs + local admin; remote-peers → Granite
  ├── forge-market-studio (:9792)   UI + harvest edge; relays data APIs to gateway
  └── IB Gateway / Edge CDP         laptop-edge routes only (no Granite relay)

Granite (public Fleet host)
  ├── Fleet API (:18766 behind Caddy/Cloudflare)
  ├── remote-peers.json             optional reverse registrations
  ├── /v1/app-gateways/market-studio[/ -dev]  → loopback market-app
  └── Postgres (forge_market)       all market/broker/wiki DB rows
```

Trust boundary for Granite mutations: [Granite operator boundary](../design/granite-operator-boundary.md) — deploy, migrate, rollout, and cutover via Fleet HTTP; no routine SSH.

## Node roles (vocabulary)

| Role | Typical host | Fleet surfaces |
|------|----------------|----------------|
| **Laptop cockpit** | Developer workstation | Local jobs, local admin, peer editor, Market thin client |
| **Coordinator / public Fleet** | Granite | Public `/v1/health`, app gateways, container services, Market rollout APIs |
| **Remote peer** | Any second Fleet with bearer | Listed in `remote-peers.json`; probed with `POST /v1/remote-peers/{id}/probe` |

Machine role (laptop vs server) is also captured in admin **Settings → Machine** and drives Edge vs Connection checklists — [Admin dashboard](../learn-101/07-admin-dashboard-and-studio.md).

## Configuration artifacts

| Artifact | Location | Purpose |
|----------|----------|---------|
| `etc/remote-peers.json` | `FLEET_DATA_DIR` | Peer id, `base_url`, `bearer_token` (secrets not returned on GET) |
| `etc/services/*.json` | `FLEET_DATA_DIR` | Managed compose (Market Studio, forge_llm, …) |
| App gateway registry | Fleet SQLite + `PUT /v1/app-gateways/{id}` | Loopback upstream for HTTPS edge (`register_edge_route` migration step) |
| Market data-plane pref | Laptop `data/operator/data-plane-pref.json` | `gateway_url`, `environment_label` when remote |

API tables: [HTTP API reference](../reference/01-http-api-reference.md) (`/v1/remote-peers/*`, `/v1/app-gateways/*`, `/v1/mesh/capacity`, `/v1/environments`).

## Operator paths

1. **Join laptop to Granite admin** — [08-connect-remote-fleet.md](../learn-101/08-connect-remote-fleet.md) (`land-fleet join` or Settings → Connection).
2. **Point Market Studio at Granite** — Settings → Granite environment; gateway URL shape in [environments.md](environments.md).
3. **Deploy or upgrade Market on Granite** — [granite-market-studio-cutover.md](granite-market-studio-cutover.md), `POST /v1/admin/forge-market-studio-rollout` (from Market Studio operator plane when configured).
4. **Publish Fleet on the server** — apt channel [09-operator-apt-install.md](../learn-101/09-operator-apt-install.md), edge [04-caddy-unified-granite.md](../build-201/04-caddy-unified-granite.md).

## Related

| Topic | Doc |
|-------|-----|
| Migration API + edge route | [09-migration-api.md](../build-201/09-migration-api.md) |
| Granite edge scheduler | [granite-market-edge-plane.md](granite-market-edge-plane.md) |
| ADR: environments | [adr-fleet-environments.md](../adr/adr-fleet-environments.md) |
| Maintainer architecture map | [03-architecture.md](../operate-301/03-architecture.md) |
