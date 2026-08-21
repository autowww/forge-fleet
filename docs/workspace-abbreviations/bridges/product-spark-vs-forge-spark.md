---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "Product Spark vs Forge Spark"
description: "Product Spark is a shippable product slice (PoC/MVP/phase); Forge Spark is a single
executable task (~1–4h) in Charge — maps to WBS Task. See NAMING-REFERENCE.md.
**Under the Epic execution profile**,"
term_category: bridge
---

# Product Spark vs Forge Spark

Product Spark is a shippable product slice (PoC/MVP/phase); Forge Spark is a single
executable task (~1–4h) in Charge — maps to WBS Task. See NAMING-REFERENCE.md.
**Under the Epic execution profile**, Charge lists Epics — see epic-vs-spark-vs-product-spark bridge.


## The collision

Plans size a "spark" afternoon task as a quarter roadmap, or label learning spikes as Sparks —
duplicate hierarchies and broken Assay/WBS traceability.

## How to choose

1) Shippable increment with Assay / milestone M1? → Product Spark (release slice).
2) Today's executable task in Charge? → Forge Spark (phase-prefixed task id) — **core Forge only**.
3) Time-boxed learning only? → discipline spike (spike_discipline) — not either Spark type.
4) Colloquial "product spike"? → discipline spike with PM lens — not Product Spark.
5) Repo under Epic execution profile? → use [epic-vs-spark-vs-product-spark](epic-vs-spark-vs-product-spark.md) instead of steps 2–4 for Charge grain.

## Using several at once

Product Spark rolls up Ingots and Forge Sparks via WBS; one ID spine when using M1E1S1T1 pattern.
forge repo abbr is unrelated to Forge Spark task noun. Epic-profile repos: Charge = Epics, not Sparks.

## Terms covered

- [**Product-Spark**](../terms/product-spark.md)
- [**Forge-Spark**](../terms/forge-spark.md)
- [**Epic-execution-profile**](../terms/epic-execution-profile.md)
- [**WBS**](../terms/wbs.md)
- [**PoC**](../terms/poc.md)
- [**MVP**](../terms/mvp.md)
- [**forge**](../terms/forge.md)
- [**Charge**](../terms/charge.md)

## Examples from chat / plan.md

"M1 MVP Spark" in roadmap → Product Spark named M1; tasks discover:oauth-config and specify:api-contract are Forge Sparks.

Exploration spike for CDP attach feasibility → spike_discipline in forge-logs — not a Forge Spark committed to Charge.

---

*Bridge page `product-spark-vs-forge-spark` — read when multiple abbreviations appear in one sentence.*
