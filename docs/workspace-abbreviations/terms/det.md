---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "det — Deterministic UX rules"
description: "KS website UX auditor deterministic checks (DET.* rule ids) — repeatable layout/hash/nav enforcement.
"
term_abbr: "det"
term_category: "ux_governance"
---

# det — Deterministic UX rules

KS website UX auditor deterministic checks (DET.* rule ids) — repeatable layout/hash/nav enforcement.


## What it is

analyze-website-ux.mjs design-rules/deterministic/*.check.js — separate from score-website-ux.mjs AI scorer.

## When people say this

When remediating UX audit findings, hash registry rows, or invoking det-ruleset harness tests.

## Where it lives

forgesdlc-kitchensink/tools/website-ux-auditor/

## How it fits the ecosystem

AI findings should propose candidate det rules when repeatable per ks-ux governance rules.

## Typical usage in plans and chat

UX remediation plans cite DET rule id (e.g. DET.NAV.BREADCRUMB) and harness --only-rule flag.

## Related terms

- [**hash**](hash.md)
- [**UX**](ux.md)
- [**PDCA**](pdca.md)

## Disambiguation bridges

- [ks-consumer-chain](../bridges/ks-consumer-chain.md)

---

*Term page — canonical catalog entry `det`.*
