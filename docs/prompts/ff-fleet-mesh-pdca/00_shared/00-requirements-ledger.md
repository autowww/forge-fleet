# Fleet Mesh — requirements ledger

All requirements for the `ff-fleet-mesh-pdca` program (FM00–FM59). Map each to gate evidence before implementing.

**Goal:** Federated Fleet nodes (mesh) with laptop cockpit/router, Class A batch placement (LAN NAS when home, Granite fallback), signed apt operator install, and phased resource/stateful/UI/DR capabilities — without replacing Fleet with a general-purpose Kubernetes scheduler.

**Baseline:** Single-host Fleet today; `remote_peers.py` proxies GET only; jobs run on receiving host. See [03-architecture.md](../../../operate-301/03-architecture.md).

---

## Cross-cutting / governance

| ID | Requirement | Phase | Gate evidence |
|----|-------------|-------|---------------|
| R00 | Preserve Granite operator boundary: mesh ops via Fleet HTTP APIs only | All | No SSH deploy in mesh runbooks; align [granite-operator-boundary.md](../../../design/granite-operator-boundary.md) |
| R01 | Document mesh vocabulary and node roles (cockpit, router, worker) | G0 | [01-assumptions-and-non-goals.md](01-assumptions-and-non-goals.md) reviewed |
| R02 | Extend peer schema: `role`, `tier` (`lan`\|`wan`), `capabilities[]`, `max_concurrent_jobs` | 1 | Schema in ledger + `remote-peers.json` example |
| R03 | Local Fleet remains cockpit when LAN peer appears; no uninstall-on-discovery | 1 | Runbook + integration test |
| R04 | Every placement returns explainable `placement_decision` (node, policy, reason) | 1 | API response field + admin job detail |
| R05 | Idempotent job submit via `meta.idempotency_key` across forward/retry | 1 | Test: duplicate POST does not double-run |

---

## Phase G0 — Ubuntu apt distribution

Operators install Fleet through **packages.forgesdlc.com** — not git. Maintainer git path (`git-install.sh`) remains for contributors only.

| ID | Requirement | Deliverable | Gate evidence |
|----|-------------|-------------|---------------|
| R06 | Publish **signed Ubuntu apt repository** at `https://packages.forgesdlc.com/fleet/ubuntu/` | `Release` + `InRelease` + `Packages` per suite (`noble`, `jammy` when ready); GPG key published | `apt update` succeeds on clean Ubuntu VM |
| R07 | Two binary packages: **`forge-fleet`** (system, `/opt`, port 18765) and **`forge-fleet-user`** (user systemd, port 18766) | `.deb` + `packaging/nfpm/`; kitchensink CSS bundled | `dpkg -l forge-fleet-user` after install |
| R08 | **Checksums** per release: `SHA256SUMS` + `SHA256SUMS.asc`; apt indices signed | CI publish step; version = Fleet SemVer from `pyproject.toml` | Verify script matches published sums |
| R09 | Package **Depends/Recommends**: `python3 (>= 3.11)`, `rsync`, `curl`; **Recommends**: Docker via meta-package | `debian/control` / nfpm metadata; `forge-fleet-docker` meta-package | `apt install forge-fleet-user --install-recommends` |
| R09a | **`apt upgrade`** updates Fleet in place; `postinst` runs `daemon-reload` + service restart | Maintainer scripts | Bump version via apt updates running binary |
| R09b | Operator install **must not require git**; git path documented as maintainer-only | Learn 101 operator vs contributor split | Runbook lint |
| R06c | Maintainer scripts: full install/upgrade/remove/purge lifecycle | preinst/postinst/prerm/postrm | FM06 gate |
| R06d | `forge-fleet.env` registered as **conffile**; upgrade never silently overwrites bearer | nfpm conffiles | apt upgrade prompts on conflict |
| R06e | `reprepro` (or equivalent) CI publishes signed `dists/noble/` on every release tag | `scripts/publish-fleet-apt-repo.sh` | FM08 gate |
| R06f | Integration test: fresh `ubuntu:noble` `apt install forge-fleet-user` → health 200 | CI or `tests/integration/` | FM09 gate |
| R06g | Purge policy: `remove` keeps SQLite; `purge` optionally deletes state (debconf) | Docs + postrm | FM06 gate |
| R06h | Bundled kitchensink CSS in deb (no submodule fetch at install) | `packaging/scripts/bundle-kitchensink-css.sh` | FM05 gate |

**Non-goal (G0):** Windows/macOS native apt packages — router-only / WSL per R18–R19.

---

## Phase 1 — Scenario A: land laptop + ephemeral batch placement

| ID | Requirement | Deliverable | Gate evidence |
|----|-------------|-------------|---------------|
| R10 | **Land Fleet on new Linux laptop** via apt bootstrap from `$HOME` (default **user** package) | `packaging/ubuntu/install.sh` + `land-fleet` CLI | Fresh VM: health 200 on `:18766` without git |
| R11 | Mesh join: register Granite peer + optional LAN NAS peer | `land-fleet join` or `PUT /v1/remote-peers/*` | `probe` green for both |
| R12 | **POST forward** allowlisted job types to worker peer | `proxy_post()` + router in `main.py` | curl job lands on NAS worker |
| R13 | `meta.placement_class: ephemeral` + `placement_policy: prefer_lan` on submit | Job schema docs + validation | Non-ephemeral defaults to local |
| R14 | Class A **allowlist** (template build, pattern rollup backfill, infra audit, image pull warm) | `placement_allowlist.py` or container type flags | pgdata-mount job rejected remotely |
| R15 | Placement router v0: tier order (lan → wan) + mem/cpu headroom from `host_stats.snapshot()` | `placement_router.py` | 10 builds prefer NAS when home |
| R16 | Fallback to Granite when LAN probe fails or capacity insufficient | `fallback_peer=granite` policy | NAS stopped → job on Granite |
| R17 | Job status/logs visible on laptop via peer GET proxy | Admin job detail | End-to-end from `/admin/` |
| R18 | **Platform policy:** Linux = Tier 1; macOS = router-only; Windows = WSL2 or remote-only | `docs/learn-101/land-fleet-laptop.md` | Doc review |
| R19 | macOS/WSL documented; no apt on macOS until launchd exists | Learn 101 platform matrix | Doc review |
| R1a | Bootstrap verifies GPG key + optional `SHA256SUMS` before first `apt install` | `install.sh` + `FLEET_VERIFY_CHECKSUMS` | Tampered index fails closed |

---

## Phase 2 — Resource operate: CPU, RAM, GPU, VRAM

| ID | Requirement | Deliverable | Gate evidence |
|----|-------------|-------------|---------------|
| R20 | `GET /v1/capacity` per node: static + dynamic from `host_stats` + reservations | New endpoint | JSON matches live host |
| R21 | Job `meta.resources`: `cpu_cores`, `mem_mb`, optional `gpu.{required,vram_mb,exclusive}` | Schema + container type defaults | Admission uses declared spec |
| R22 | **Reservation ledger** on worker: reserve on admit, release on terminal | SQLite table in `store.py` | Concurrent submits do not OOM |
| R23 | Router aggregates peer capacity (cached 15–30s) | `GET /v1/mesh/capacity` on laptop | Admin Workers card |
| R24 | GPU index selection + inject `--gpus device=N` for NVIDIA workers | Runner hook from placement result | GPU job exclusive on one index |
| R25 | Static GPU reservations for known tenants (e.g. forge-llm on Granite GPU 0) | Node config `gpu_reserved[]` | smi free + reserved = schedulable |
| R26 | Node **degraded** cooldown after OOM/probe failures | `store.py` cooldown + router skip | Node excluded N minutes after OOM |
| R27 | macOS `host_stats` fallback OR router-only (no local worker admission) | `host_stats.py` or policy flag | Documented behavior |

---

## Phase 3 — Stateful services and data gravity

| ID | Requirement | Deliverable | Gate evidence |
|----|-------------|-------------|---------------|
| R30 | Environment records gain `replication_class`, `data_gravity`, `allowed_hosts[]` | Extend `environment.schema.json` | ADR accepted |
| R31 | Class B: optional read replica on LAN via scheduled `seed: replicate` | Infra flow + runbook | Nightly prod→LAN dev |
| R32 | Class C: **single primary** model; LAN write = controlled promotion failover only | Failover runbook using migration API | Drill: promote → smoke → failback |
| R33 | Jobs with `network_egress_sensitive` require reachable DSN from chosen node | Router constraint | Backfill skips NAS if PG unreachable |
| R34 | Rollout slots per `container_service_id` preserved across mesh | Document + 409 behavior | granite-market-studio-environments parity |

---

## Phase 4 — Plan loop and placement UI

| ID | Requirement | Deliverable | Gate evidence |
|----|-------------|-------------|---------------|
| R40 | Historical job profiles (p50/p95 mem/cpu/gpu) from telemetry + job meta | Profile store / rollup | Default ResourceSpec per job type |
| R41 | **Propose placement** API: dry-run move/score without apply | `POST /v1/placement/propose` | Returns violations + score |
| R42 | Admin **Workers** heatmap: per-node CPU/RAM/GPU headroom | `/admin/` panel | Matches mesh capacity |
| R43 | Apply placement via safe flow (stop → migrate/redeploy → health) | Propose → confirm → execute | Illegal moves blocked |
| R44 | Optional mDNS `_forge-fleet._tcp` LAN discovery | `discovery.py` + enroll | NAS auto-appears at home |

---

## Phase 5 — Resilience, LB clusters, live backup

| ID | Requirement | Deliverable | Gate evidence |
|----|-------------|-------------|---------------|
| R50 | Flexible LB for web/calc worker pools (Caddy/Traefik upstream registry) | Edge config + Fleet service registry | Multi-backend health check |
| R51 | Postgres WAL/archive backups via Fleet-scheduled jobs (pgBackRest/WAL-G) | Infra flow `.lmeta` | Restore drill |
| R52 | Coordinator failover policy documented (Granite tie-breaker vs elected) | ADR | Drill script |
| R53 | RPO/RTO per app tier in runbooks | Operator docs | Market Studio prod RPO stated |
| R54 | DR drill: node loss → jobs retry on peer; stateful failback documented | `FM54` leaf | Quarterly evidence |

---

## Non-functional requirements

| ID | NFR | Target |
|----|-----|--------|
| NFR01 | Security | Peer bearer tokens; `remote-peers.json` mode 600; no Granite SSH for mesh ops |
| NFR02 | Explainability | 100% of auto-placements include human-readable reason |
| NFR03 | Fail-safe defaults | Missing `placement_class` → local execution |
| NFR04 | Session-safe ops | Install/land scripts sequential; no parallel shell fan-out on operator workstation |
| NFR05 | Backward compatibility | Single-host Fleet without peers behaves exactly as today |
| NFR06 | Observability | Placement decisions logged; mesh capacity refresh <30s stale |
| NFR07 | Platform | Phase 1 production path = Linux apt; macOS router-only; Windows via WSL2 apt |
| NFR08 | Supply chain | Operator binaries from signed apt repo; checksums published; pipe-to-bash only with GPG-verified apt source |

---

## Explicit non-goals (by phase)

| Phase | Non-goals |
|-------|-----------|
| G0b | Git-based operator install; unsigned `.deb` without apt/GPG |
| 1 | Drag-drop UI; live DB sync; moving running compose stacks; native Windows Fleet; K8s replacement |
| 2 | Fractional GPU/MIG; ML-based placement; infer resources from `docker_argv` without declarations |
| 3 | Multi-master Postgres; automatic split-brain resolution |
| 4 | Unconstrained drag-drop without validation |
| 5 | Full auto-failover without operator-approved cutover |

---

## PDCA phase mapping (summary)

| Wave | Phases | Primary requirements |
|------|--------|---------------------|
| MW-0 | FM00–FM02 | R00–R05, R01 |
| MW-0b | FM05–FM09 | R06–R09, R06c–R06h, R1a, R10 (install path) |
| MW-1 | FM10–FM19 | R02–R05, R10–R19 |
| MW-2 | FM20–FM29 | R20–R27 |
| MW-3 | FM30–FM39 | R30–R34 |
| MW-4 | FM40–FM49 | R40–R44 |
| MW-5 | FM50–FM59 | R50–R54 |

**Assumptions:** See [01-assumptions-and-non-goals.md](01-assumptions-and-non-goals.md). **Open questions:** [02-open-questions-ledger.md](02-open-questions-ledger.md). One phase per commit; gate before next phase.
