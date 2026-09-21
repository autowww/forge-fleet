# Forge Fleet Mesh PDCA — master sequence

Composer **2.5** implements phases **FM00–FM02** (Wave MW-0), **FM05–FM09** (MW-0b apt distribution), **FM10–FM19** (MW-1 Scenario A), **FM20–FM29** (MW-2 resource operate), **FM30–FM39** (MW-3 stateful/data gravity), **FM40–FM49** (MW-4 plan loop + UI), and **FM50–FM59** (MW-5 resilience + closeout).

**Requirements source:** [00_shared/00-requirements-ledger.md](00_shared/00-requirements-ledger.md) (R00–R54, NFR01–NFR08)

**Operator boundary:** [granite-operator-boundary.md](../../design/granite-operator-boundary.md) — Granite SSH **only** for Fleet daemon upgrade; mesh ops via Fleet HTTP.

**Operator install:** signed apt repo at `https://packages.forgesdlc.com/fleet/ubuntu/` — not git (see [01-assumptions-and-non-goals.md](00_shared/01-assumptions-and-non-goals.md)).

Executor model: **Composer 2.5** (standard variant, not `-fast`).

| Wave | Phases | Theme |
|------|--------|-------|
| MW-0 | FM00–FM02 | Scaffold, requirements, peer schema ADR |
| MW-0b | FM05–FM09 | Debian packaging, apt repo, `install.sh`, checksums |
| MW-1 | FM10–FM19 | Land laptop (apt), mesh join, POST forward, router v0 |
| MW-2 | FM20–FM29 | Capacity API, reservations, GPU admission |
| MW-3 | FM30–FM39 | Replication classes, controlled failover |
| MW-4 | FM40–FM49 | Profiles, propose/apply placement, Workers UI |
| MW-5 | FM50–FM59 | LB, backups, DR drills, closeout |

---

## MW-0 — Scaffold and governance

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FM00 | [FM00-pdca-scaffold.md](FM00-pdca-scaffold.md) | — | PDCA harness + master sequence |
| FM01 | FM01-requirements-ledger.md | R00–R05, R10–R19 | Ledger review + cross-links |
| FM02 | FM02-peer-schema-adr.md | R02 | ADR: extended `remote-peers.json` schema |

---

## MW-0b — Ubuntu apt distribution

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FM05 | [FM05-nfpm-deb-scaffold.md](FM05-nfpm-deb-scaffold.md) | R07, R06h | `packaging/nfpm/*.yaml` + first local `.deb` build |
| FM06 | [FM06-deb-maintainer-scripts.md](FM06-deb-maintainer-scripts.md) | R06c, R06d, R06g | preinst/postinst/prerm/postrm + conffiles |
| FM07 | [FM07-forge-fleet-docker-meta.md](FM07-forge-fleet-docker-meta.md) | R09, Q08 | `forge-fleet-docker` meta-package + Docker CE repo |
| FM08 | [FM08-apt-repo-publish.md](FM08-apt-repo-publish.md) | R06, R06e, R08 | `reprepro` + GPG signing + CI publish to staging CDN |
| FM09 | [FM09-install-sh-cutover.md](FM09-install-sh-cutover.md) | R10, R1a, R06f | `install.sh` + `SHA256SUMS` + noble integration test |

---

## MW-1 — Scenario A: ephemeral batch placement

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FM10 | FM10-proxy-post-forward.md | R12 | `proxy_post()` in `remote_peers.py` |
| FM11 | FM11-placement-meta-schema.md | R13, R14 | `placement_class`, allowlist |
| FM12 | FM12-placement-router-v0.md | R15, R16 | LAN-first router + Granite fallback |
| FM13 | FM13-placement-decision-api.md | R04, R05 | `placement_decision` + idempotency |
| FM14 | FM14-land-fleet-cli.md | R10, R11 | `/usr/bin/land-fleet` mesh join |
| FM15 | FM15-admin-placement-ui.md | R17 | Job detail shows `placed_on` + reason |
| FM16 | FM16-land-fleet-laptop-docs.md | R18, R19, R09b | Learn 101 operator vs contributor paths |
| FM17 | FM17-scenario-a-integration.md | R03 | Integration tests: LAN → Granite fallback |
| FM18 | FM18-scenario-a-e2e.md | R10–R17 | Proof ladder on staging mesh |
| FM19 | FM19-mw1-closeout.md | — | MW-1 gate |

---

## MW-2 — Resource operate (stub sequence)

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FM20 | FM20-capacity-endpoint.md | R20 | `GET /v1/capacity` |
| FM21 | FM21-resource-spec-meta.md | R21 | Job `meta.resources` |
| FM22 | FM22-reservation-ledger.md | R22 | SQLite reservations |
| FM23 | FM23-mesh-capacity-aggregate.md | R23 | `GET /v1/mesh/capacity` |
| FM24 | FM24-gpu-placement.md | R24, R25 | GPU index + `--gpus` inject |
| FM25 | FM25-node-degraded-cooldown.md | R26 | OOM/probe degraded state |
| FM26 | FM26-macos-host-stats.md | R27 | vm_stat fallback or router-only policy |
| FM29 | FM29-mw2-closeout.md | — | MW-2 gate |

---

## MW-3 — Stateful / data gravity (stub sequence)

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FM30 | FM30-replication-class-schema.md | R30 | Environment schema extension |
| FM31 | FM31-lan-read-replica-runbook.md | R31 | Scheduled replicate prod→LAN |
| FM32 | FM32-controlled-failover-drill.md | R32 | Single-primary promotion runbook |
| FM33 | FM33-network-egress-constraint.md | R33 | DSN reachability in router |
| FM34 | FM34-rollout-slot-mesh-doc.md | R34 | Cross-mesh rollout slot policy |
| FM39 | FM39-mw3-closeout.md | — | MW-3 gate |

---

## MW-4 — Plan loop + UI (stub sequence)

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FM40 | FM40-job-profile-rollup.md | R40 | Historical p50/p95 profiles |
| FM41 | FM41-placement-propose-api.md | R41 | `POST /v1/placement/propose` |
| FM42 | FM42-workers-heatmap-admin.md | R42 | Admin Workers panel |
| FM43 | FM43-placement-apply-flow.md | R43 | Propose → confirm → execute |
| FM44 | FM44-mdns-lan-discovery.md | R44 | Optional `_forge-fleet._tcp` |
| FM49 | FM49-mw4-closeout.md | — | MW-4 gate |

---

## MW-5 — Resilience + closeout (stub sequence)

| Phase | Prompt | Req | Scope |
|-------|--------|-----|-------|
| FM50 | FM50-lb-worker-pools.md | R50 | Caddy/Traefik upstream registry |
| FM51 | FM51-postgres-wal-backup-flow.md | R51 | pgBackRest/WAL-G infra flow |
| FM52 | FM52-coordinator-failover-adr.md | R52 | Coordinator policy ADR |
| FM53 | FM53-rpo-rto-runbooks.md | R53 | Per-app RPO/RTO docs |
| FM54 | FM54-dr-drill-leaf.md | R54 | Node loss + failback drill |
| FM59 | FM59-program-closeout.md | — | Program closeout |

---

## Phase 1 proof ladder (Scenario A acceptance)

1. Laptop joins mesh (Granite + LAN NAS visible in admin).
2. Container template build auto-placed on NAS when LAN healthy.
3. Same build routes to Granite when NAS peer down.
4. Placement reason visible in API/admin.
