---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "Kitchen Sink consumer chain"
description: "ks primitives flow ks → fa (autodoc) → bp/bpw/forge public sites and private handbook shells;
edit ks first, then bump submodules per consumer — never only the embedded copy.
"
term_category: bridge
---

# Kitchen Sink consumer chain

ks primitives flow ks → fa (autodoc) → bp/bpw/forge public sites and private handbook shells;
edit ks first, then bump submodules per consumer — never only the embedded copy.


## The collision

Developer patches kitchensink/ inside forgesdlc submodule without pushing ks standalone —
next sync overwrites fix; missing hash/contract updates break det audits.

## How to choose

1) New/changed layout, component, CSS primitive, auditor rule? → commit ks, build-showcase.py.
2) Handbook build pipeline change? → fa in ks, then consumers.
3) Site-specific content only? → consumer repo (forge, bpw) without ks primitive change.
4) Propagate everywhere? → ./sync-kitchensink-and-rebuild.sh from Code root.

## Using several at once

bp consumes process not ks for methodology text, but bpw/forgesdlc/handbook shells all submodule ks.
det + hash governance lives in ks tools/website-ux-auditor.

## Terms covered

- [**ks**](../terms/ks.md)
- [**fa**](../terms/fa.md)
- [**bp**](../terms/bp.md)
- [**bpw**](../terms/bpw.md)
- [**forge**](../terms/forge.md)
- [**hash**](../terms/hash.md)
- [**det**](../terms/det.md)

## Examples from chat / plan.md

New gallery_page layout → ks components/layouts.py → showcase build → bump forge + bpw submodule → respective site builds.

DET.NAV.BREADCRUMB fix → ks check.js + contract → propagate ks → run analyze-website-ux.mjs on bpw website/ output.

---

*Bridge page `ks-consumer-chain` — read when multiple abbreviations appear in one sentence.*
