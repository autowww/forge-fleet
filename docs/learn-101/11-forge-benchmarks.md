# Learn 101 — Forge Benchmarks

**Outcome:** you can read cluster answers, per-workload rates, and stage detail on one Benchmarks page, launch a run from the same tab, and see a short composite summary on Capacity.

**Audience:** operators comparing Fleet hosts. **Time:** ~15 minutes. **Verify:** **`GET /v1/mesh/benchmarks`** returns `composite_model: additive_two_thread` and a `cluster_score`.

Forge Benchmarks live on **`/admin/` → Benchmarks** as a single scroll: answer cards (what 100 means, additive index, coverage), all five workload bar groups, a node table, run controls, and the full stage grid. **Capacity** keeps guardians and a compact composite table next to live headroom; it does not start a run. Two measurements stay in different columns and different files.

| Measurement | What it is | Where it is stored |
| --- | --- | --- |
| **Hardware** | In-process Fleet mark: one core, all cores, a memory copy, and a 256 MB file. No Docker and no SQL. | `etc/host-profile.json` under `benchmark` |
| **Market Studio** | FMSBench in containers: PostgreSQL, DuckDB, SQLite, NumPy, and a 1 GiB NLP table. | `etc/fmsbench-result.json`, `fmsbench-suite/results/`, and `etc/forge-benchmarks/reports/` |

The hardware mark is not an input to the Market Studio composite. Mesh headroom (CPU, RAM, GPU) stays under **Settings… → Capacity** and is a planning estimate, not a benchmark score.

## What you can run

| Control | Effect |
| --- | --- |
| **Re-run all hardware** | Hardware mark on this host and every configured peer. |
| **Re-run all Market Studio** | Market Studio **standard** profile on this host and every configured peer. |
| **This peer · hardware** | Hardware mark on the selected peer only. |
| **This peer · Market Studio** | The profile chosen in the menu, on the selected peer only. |

| Profile | What runs |
| --- | --- |
| **standard** | Comparable dataset. Threads and workers are 8. This is the composite source. |
| **host-max-cores** | Same dataset. Threads and workers equal the physical core count. Saved beside standard. |
| **host-max-threads** | Same dataset. Threads and workers equal the hardware thread count. Saved beside standard. |
| **stress** | Same dataset at twice the hardware thread count. Separate stress score. Does not replace standard. |
| **full** | Standard, then host-max-cores, then host-max-threads, then stress. |
| **smoke** and **micro** | Short install checks. They replace the displayed Market Studio result and are not the composite source. |

Work files, containers, and the runner image are removed after a run. Result JSON is kept. **`POST /v1/host/profile/fmsbench/cleanup`** repeats that cleanup.

## Composite and cluster

The composite uses **two-thread throughput** from the standard run. Each stage is `weight × (this host's rate / this server's rate)`. This server scores **100**. A host that is twice as fast on every stage scores **200**.

| Stage | Weight | Rate |
| --- | --- | --- |
| DuckDB | 28 | Completed bundles per second |
| NLP | 28 | Documents per second against one shared 1 GiB embedding table |
| PostgreSQL | 22 | Completed bundles per second |
| Compute | 12 | NumPy rows per second |
| SQLite | 10 | Completed bundles per second |

**Cluster** (`cluster_score` on the API) is an **additive capacity index**: the sum of comparable composites, in units of this server. Two hosts at 100 and 80 add to 180 index points. That sum is not verified distributed throughput and does not prove 1.8× end-to-end parallel speedup across the mesh.

NLP is included only when both this server and the peer have a measured NLP stage. Until then the other four weights are scaled back to 100. Once this server has NLP, a peer without it is marked **partial** and left out of the cluster total.

Stress, host-max-cores, and host-max-threads are separate columns. They are not folded into the composite.

The NLP stage is one shared table of 262,144 vectors by 1,024 float32 values (1 GiB). Threads read that table. They do not allocate a copy per thread.

## API

| Call | Role |
| --- | --- |
| `GET /v1/mesh/benchmarks` | Comparison rows, composite weights, `cluster_score` |
| `POST /v1/mesh/benchmarks/run` | Body `{"suite":"hardware"}` or `{"suite":"market_studio","profile":"standard"}` |
| `POST /v1/host/profile/benchmark` | Hardware mark on this host |
| `POST /v1/host/profile/fmsbench` | Market Studio run. Body `{"profile":"<name>"}` |
| `POST /v1/remote-peers/{id}/host/profile/fmsbench` | Same run on a peer |

Route list: **[HTTP API](../reference/01-http-api-reference.md)**.

## Related

| Topic | Doc |
| --- | --- |
| Admin tabs | **[Admin dashboard and Studio](07-admin-dashboard-and-studio.md)** |
| Mesh headroom | **[Connect to remote Fleet](08-connect-remote-fleet.md)** |
| Disk and RAM guardians | **[Space Guardian](../maintainers/06-space-guardian.md)** · **[Memory Guardian](../maintainers/07-memory-guardian.md)** |
