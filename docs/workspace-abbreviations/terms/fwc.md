---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "fwc — Forge Workcells"
description: "Private workcell runners — local_llm_worker, pack loader; domain micro-packs stay in ks.
"
term_abbr: "fwc"
term_category: "repo"
---

# fwc — Forge Workcells

Private workcell runners — local_llm_worker, pack loader; domain micro-packs stay in ks.


## What it is

forge-workcells/ CLI: forge-workcells run --workcell local_llm_worker. Products must not submodule fp.

## When people say this

When running bounded agent workcells, loading KS micro-packs, or wiring Fleet job argv.

## Where it lives

forge-workcells/

## How it fits the ecosystem

KS/Lenses may submodule fwc via SSH. Part of control-plane stack with fl, fp, ff, lcdl.

## Typical usage in plans and chat

Workcell id local_llm_worker is the MVP path; relate to fllm spoken shorthand for local LLM execution.

## Related terms

- [**fp**](fp.md)
- [**ks**](ks.md)
- [**fllm**](fllm.md)
- [**ff**](ff.md)

## Disambiguation bridges

- [control-plane-stack](../bridges/control-plane-stack.md)

---

*Term page — canonical catalog entry `fwc`.*
