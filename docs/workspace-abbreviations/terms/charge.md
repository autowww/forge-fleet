---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "Charge — Charge (daily commitment view)"
description: "Daily commitment **view** — not a Kanban system of record. **Dual profile:** core Forge lists today's **Forge Sparks**;
**Epic execution profile** lists today's **Epics** (`M1E3`) with OpenSpec accept"
term_abbr: "Charge"
term_category: "lifecycle"
---

# Charge — Charge (daily commitment view)

Daily commitment **view** — not a Kanban system of record. **Dual profile:** core Forge lists today's **Forge Sparks**;
**Epic execution profile** lists today's **Epics** (`M1E3`) with OpenSpec acceptance.


## What it is

forge/charge.md — **Active Sparks** table (core) or **Active Epics** table (Epic execution profile).
Humans select what is in play today; agents execute inside that selection.

## When people say this

When updating daily commitment, standup scope, or detecting which delivery profile a repo uses (table shape).

## Where it lives

blueprints/sdlc/methodologies/forge/daily/charge.template.md; docs/forge/charge.md in consuming repos

## How it fits the ecosystem

Core Forge keeps Ore → Ingot → Forge Spark → Charge. Epic execution profile is an opt-in overlay — Charge grain switches to Epics;
Spark is not removed from Forge globally. Distinct from Forge Campaign (multi-repo automation).

## Typical usage in plans and chat

Detect profile before minting Charge rows — Sparks (core) vs Epics (profile); never mix both grains on one Charge table.
Under the Epic execution profile, do not mint Forge Sparks or WBS Task rows on Charge.

## Do not confuse with

Forge-Campaign

## Related terms

- [**Forge-Spark**](forge-spark.md)
- [**Epic-execution-profile**](epic-execution-profile.md)
- [**Product-Spark**](product-spark.md)
- [**WBS**](wbs.md)

## Disambiguation bridges

- [epic-vs-spark-vs-product-spark](../bridges/epic-vs-spark-vs-product-spark.md)

---

*Term page — canonical catalog entry `charge`.*
