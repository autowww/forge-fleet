---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "Cursor plan-chat vocabulary"
description: "Shared terms for agent planning — PDCA remediation, DoR gates, Versona reviews,
subagent tiering, and XS–XL triage sizes from forge-triage.mdc.
"
term_category: bridge
---

# Cursor plan-chat vocabulary

Shared terms for agent planning — PDCA remediation, DoR gates, Versona reviews,
subagent tiering, and XS–XL triage sizes from forge-triage.mdc.


## The collision

Plans omit acceptance loops, mis-size L work as XS, or conflate DoR with DoD —
expensive agent runs without checkpoints.

## How to choose

1) Emit triage line first (XS–XL) sizing underlying work not just "write a plan" utterance.
2) L/XL? → forge-planning-standards: phases, tests, PDCA per phase, drift gate, model tiers.
3) Roadmap not ready? → cite DoR before WBS; suggest Product Management Versona session.
4) Discipline challenge needed? → named Versona (BA, ARCH, UX, …) — §5 output optional.
5) Mechanical breadth? → subagent (explore/shell) on cheaper tier; parent keeps integration.

## Using several at once

PDCA + DoD define done per phase; DoR defines ready to start; Versona sessions live in forge-logs/ not calendar meetings.
Estimation Versona owns method; triage sizes gate orchestration cost separate from story points.

## Terms covered

- [**PDCA**](../terms/pdca.md)
- [**DoR**](../terms/dor.md)
- [**DoD**](../terms/dod.md)
- [**Versona**](../terms/versona.md)
- [**subagent**](../terms/subagent.md)
- [**XS**](../terms/xs.md)
- [**S**](../terms/s.md)
- [**M**](../terms/m.md)
- [**L**](../terms/l.md)
- [**XL**](../terms/xl.md)
- [**WBS**](../terms/wbs.md)

## Examples from chat / plan.md

User: "Plan LCDL break-in for mail ingest" → Triage: L · cross-repo → phases with lcdl tasks first, cockpit bridge second, PDCA harness per phase, ARCH Versona suggested for attach-owner invariant.

User: "fix typo in README" → Triage: XS · single file → no subagents, no PDCA table.

---

*Bridge page `plan-chat-vocabulary` — read when multiple abbreviations appear in one sentence.*
