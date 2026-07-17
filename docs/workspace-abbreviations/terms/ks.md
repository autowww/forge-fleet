---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "ks — Kitchen Sink (design system)"
description: "Shared design system — CSS themes, Python UI components, SVG templates, forge-autodoc, UX auditor tooling.
"
term_abbr: "ks"
term_category: "repo"
---

# ks — Kitchen Sink (design system)

Shared design system — CSS themes, Python UI components, SVG templates, forge-autodoc, UX auditor tooling.


## What it is

forgesdlc-kitchensink/ (autowww/forgesdlc-kitchensink). Edit primitives here first;
consumers bump kitchensink/ submodule pointers.

## When people say this

When adding layouts, components, visual hashes, design contracts, or propagating KS across sites.

## Where it lives

forgesdlc-kitchensink/

## How it fits the ecosystem

Submodule in forge, bpw, fl, ff, s8w, handbook shells, and most Forge products.
Run ./sync-kitchensink-and-rebuild.sh from Code workspace root to propagate.

## Typical usage in plans and chat

KS changes require ks commit first, then per-consumer submodule bumps. Mention det rules when UX auditing.

## Related terms

- [**fa**](fa.md)
- [**bpw**](bpw.md)
- [**forge**](forge.md)
- [**hash**](hash.md)

## Disambiguation bridges

- [ks-consumer-chain](../bridges/ks-consumer-chain.md)

---

*Term page — canonical catalog entry `ks`.*
