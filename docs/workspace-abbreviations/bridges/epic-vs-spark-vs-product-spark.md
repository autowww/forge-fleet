---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "Epic vs Product Spark vs Forge Spark (dual profile)"
description: "**Core Forge:** Charge = today's Forge Sparks (WBS Tasks). **Epic execution profile:** Charge = today's Epics (`M1E3`);
Story/Task/Forge Spark are L1–L2 agent scratch inside the Epic — not Charge rows"
term_category: bridge
---

# Epic vs Product Spark vs Forge Spark (dual profile)

**Core Forge:** Charge = today's Forge Sparks (WBS Tasks). **Epic execution profile:** Charge = today's Epics (`M1E3`);
Story/Task/Forge Spark are L1–L2 agent scratch inside the Epic — not Charge rows. Product Spark stays release/Assay horizon in both profiles.


## The collision

Agents mint Forge Sparks on Charge in Epic-profile repos, treat Epics as Product Sparks, or build parallel WBS Task backlogs —
broken OpenSpec traceability and duplicate Charge hierarchies.

## How to choose

1) Detect profile — forge.config.yaml, docs/PROJECT.md, or Charge table (**Active Sparks** vs **Active Epics**).
2) Shippable increment / Assay / milestone M1? → **Product Spark** (both profiles).
3) **Epic execution profile** + ready Epic (OpenSpec size gate, one repo, reviewable diff)? → **Charge Epic** (`M1E3`) — not Forge Spark.
4) **Epic execution profile** + work inside Charged Epic? → L1–L2 **runs** — not Charge rows, not `…T{n}` WBS Tasks, not tasks.md merge gates.
5) Time-boxed learning only? → **discipline spike** (spike_discipline) — not Product Spark, Forge Spark, or Charged Epic.
6) **Core Forge** — today's executable task in Charge? → **Forge Spark** (phase-prefixed task id).
7) **Core Forge** — colloquial sizing only? → re-check steps 2 and 6; use product-spark-vs-forge-spark for Spark collisions.

## Using several at once

Dual profile: core keeps Ore → Ingot → Forge Spark → Charge. Overlay switches Charge grain to Epics with OpenSpec 1:1.
Do not imply Spark is deleted from Forge — teams choose profile per repo. WBS Epic IDs align with committed Epics under profile only.

## Terms covered

- [**Epic-execution-profile**](../terms/epic-execution-profile.md)
- [**Product-Spark**](../terms/product-spark.md)
- [**Forge-Spark**](../terms/forge-spark.md)
- [**Charge**](../terms/charge.md)
- [**WBS**](../terms/wbs.md)

## Examples from chat / plan.md

forge-lenses under profile → Charge M1E3 with openspec/ change; agents classify → plan → apply inside Epic — no discover:foo Spark on Charge.

Core product repo → Charge lists discover:api-schema Forge Spark; WBS M1E1S1T1 aligns Task and Spark on one ID spine.

---

*Bridge page `epic-vs-spark-vs-product-spark` — read when multiple abbreviations appear in one sentence.*
