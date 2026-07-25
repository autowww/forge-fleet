---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "fllm — Local LLM execution (informal)"
description: "Informal shorthand for on-device / local LLM worker paths — not a separate git repo abbreviation.
"
term_abbr: "fllm"
term_category: "platform"
---

# fllm — Local LLM execution (informal)

Informal shorthand for on-device / local LLM worker paths — not a separate git repo abbreviation.


## What it is

Maps to fwc local_llm_worker workcell, optional local inference endpoints, and lcdl transport to local models.

## When people say this

When discussing private LLM workers, forge-workcells runs, or avoiding cloud API for a task.

## Where it lives

forge-workcells/ (primary); lcdl tasks; ks micro-packs

## How it fits the ecosystem

fwc runs --workcell local_llm_worker. Domain packs in ks tools/forge-micro-agent/packs/.

## Typical usage in plans and chat

Prefer fwc + workcell id in formal plans; fllm acceptable in chat if scope is clearly local inference.

## Do not confuse with

lcdl
fwc

## Related terms

- [**fwc**](fwc.md)
- [**lcdl**](lcdl.md)
- [**ks**](ks.md)

---

*Term page — canonical catalog entry `fllm`.*
