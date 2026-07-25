---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "XS — Triage size XS"
description: "Extra-small agent request — heuristic <5k tokens; inline work, no heavy orchestration.
"
term_abbr: "XS"
term_category: "cursor_plan"
---

# XS — Triage size XS

Extra-small agent request — heuristic <5k tokens; inline work, no heavy orchestration.


## What it is

forge-triage.mdc emits Triage: XS (~<5k) · rationale as first line of agent responses.

## When people say this

Single-file typo, tiny config tweak, one-line clarification — skip subagent armies.

## Where it lives

.cursor/rules/forge-triage.mdc

## How it fits the ecosystem

Anchors are self-estimates not measured billing tokens — use relative sizing consistency.

## Typical usage in plans and chat

XS requests should not include multi-phase PDCA tables — answer directly.

## Related terms

- [**S**](s.md)
- [**M**](m.md)
- [**L**](l.md)
- [**XL**](xl.md)
- [**subagent**](subagent.md)

## Disambiguation bridges

- [plan-chat-vocabulary](../bridges/plan-chat-vocabulary.md)

---

*Term page — canonical catalog entry `xs`.*
