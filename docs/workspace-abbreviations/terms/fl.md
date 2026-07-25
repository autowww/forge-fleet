---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "fl — Forge Lenses"
description: "Local-first workspace control plane — lenses Python package, Studio on /studio/, Classic dashboard on :8080.
"
term_abbr: "fl"
term_category: "repo"
---

# fl — Forge Lenses

Local-first workspace control plane — lenses Python package, Studio on /studio/, Classic dashboard on :8080.


## What it is

forge-lenses/ standalone clone (not embedded submodule in other workspace repos).
Tracks .lenses-local/ (ignored) and .lenses-repo/<github-login>/ overlays.

## When people say this

When running python3 -m lenses, Studio explore, repo snapshots, or Lenses handbook content.

## Where it lives

forge-lenses/

## How it fits the ecosystem

Control-plane peer with fp, ff, fwc, lcdl. Handbook deploy via flsw → Firebase lenses-d0fdb.

## Typical usage in plans and chat

"Lenses" or "forge-lenses" in chat maps to fl. Wizard and FTS live under .lenses-local/.

## Do not confuse with

flsw

## Related terms

- [**flsw**](flsw.md)
- [**fp**](fp.md)
- [**ff**](ff.md)
- [**bp**](bp.md)
- [**ks**](ks.md)

## Disambiguation bridges

- [handbook-deploy-pairs](../bridges/handbook-deploy-pairs.md)
- [control-plane-stack](../bridges/control-plane-stack.md)

---

*Term page — canonical catalog entry `fl`.*
