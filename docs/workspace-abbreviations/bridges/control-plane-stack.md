---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "Forge control-plane stack"
description: "fl (workspace visibility), fp (platform contracts), ff (job execution), fwc (workcells),
lcdl (governed LLM) — complementary layers operators compose; not one monorepo.
"
term_category: bridge
---

# Forge control-plane stack

fl (workspace visibility), fp (platform contracts), ff (job execution), fwc (workcells),
lcdl (governed LLM) — complementary layers operators compose; not one monorepo.


## The collision

Feature placed in wrong layer — e.g. Docker job orchestration coded in Lenses, or LLM parse logic in Fleet SQLite admin.

## How to choose

1) Inspect/guide repos, Studio, local FTS? → fl.
2) ForgeRun, AgentRun, campaign schemas, ADRs? → fp (handbook fpw).
3) Bearer-gated docker_argv jobs, git-self-update? → ff.
4) Pack/workcell execution, local_llm_worker? → fwc.
5) Governed LLM task/operator, OWA atoms? → lcdl.
6) Cross-cutting doc? → Platform handbook + Lenses handbook — link, don't duplicate.

## Using several at once

Cockpit ingest orchestrates lcdl+cdp+ff but is not listed as core schema owner —
control-plane docs in fp tie the narrative; fl surfaces workspace health.

## Terms covered

- [**fl**](../terms/fl.md)
- [**fp**](../terms/fp.md)
- [**ff**](../terms/ff.md)
- [**fwc**](../terms/fwc.md)
- [**lcdl**](../terms/lcdl.md)
- [**fpw**](../terms/fpw.md)
- [**flsw**](../terms/flsw.md)

## Examples from chat / plan.md

Docs Health job → ff schedules container; fl may display outcome; lcdl not required unless LLM break-in enabled.

New EvidencePacket field → fp schema first; consumers (fwc, ff jobs) bump against fp handbook contract.

---

*Bridge page `control-plane-stack` — read when multiple abbreviations appear in one sentence.*
