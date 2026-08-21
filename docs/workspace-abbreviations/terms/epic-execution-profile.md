---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "Epic-execution-profile — Epic execution profile"
description: "Opt-in overlay on core Forge — Charge lists **Epics**; smallest committed unit = L3 Epic (`M1E3`) with OpenSpec acceptance;
agents decompose **runs** inside a Charged Epic, not WBS Task Charge rows.
"
term_abbr: "Epic-execution-profile"
term_category: "lifecycle"
---

# Epic-execution-profile — Epic execution profile

Opt-in overlay on core Forge — Charge lists **Epics**; smallest committed unit = L3 Epic (`M1E3`) with OpenSpec acceptance;
agents decompose **runs** inside a Charged Epic, not WBS Task Charge rows.


## What it is

Canon in EPIC-EXECUTION-PROFILE.md. One OpenSpec change 1:1 with a ready Epic; Lite SHALLs + scenarios default;
tasks.md is non-binding agent scratch. Detect via forge/forge.config.yaml, docs/PROJECT.md, or Charge **Active Epics** table.

## When people say this

When a repo opts into L3 Epic + OpenSpec delivery, or any doc says **under the Epic execution profile**.

## Where it lives

blueprints/sdlc/methodologies/forge/EPIC-EXECUTION-PROFILE.md

## How it fits the ecosystem

Dual profile: core teams keep Spark → Charge unchanged. Profile teams Charge Epics; Story/Task/Forge Spark are L1–L2 scratch inside the Epic.
Product Spark remains release/Assay horizon. L4+ (ADR, cross-repo) → agents stop and ask.

## Typical usage in plans and chat

Qualify Epic-specific behavior with **under the Epic execution profile** — never imply Spark is deleted from all Forge teams.
Pilot repos (e.g. forge-lenses) may use profile while sibling repos stay core Spark → Charge.

## Do not confuse with

Forge-Spark
Charge
Product-Spark
WBS

## Related terms

- [**Charge**](charge.md)
- [**Forge-Spark**](forge-spark.md)
- [**Product-Spark**](product-spark.md)
- [**WBS**](wbs.md)

## Disambiguation bridges

- [epic-vs-spark-vs-product-spark](../bridges/epic-vs-spark-vs-product-spark.md)
- [product-spark-vs-forge-spark](../bridges/product-spark-vs-forge-spark.md)

---

*Term page — canonical catalog entry `epic-execution-profile`.*
