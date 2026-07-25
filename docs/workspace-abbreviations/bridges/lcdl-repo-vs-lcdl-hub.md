---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "forge-lcdl library vs ~/LCDL/ hub"
description: "lcdl is the Python package under Code/forge-lcdl/; LCDL-hub is a home-directory multi-repo folder
that is not a git repository and is not where the library source lives.
"
term_category: bridge
---

# forge-lcdl library vs ~/LCDL/ hub

lcdl is the Python package under Code/forge-lcdl/; LCDL-hub is a home-directory multi-repo folder
that is not a git repository and is not where the library source lives.


## The collision

Chat says "clone LCDL" or "work in LCDL" — agent picks wrong path, pip installs from
~/LCDL/, or confuses hub with A11y/LCDL product naming.

## How to choose

1) Governing LLM tasks, operators, pip install -e? → Code/forge-lcdl/ (lcdl).
2) Personal workspace with lenses+composer beside each other? → ~/LCDL/ (LCDL-hub).
3) Handbook deploy? → flw submodules forge-lcdl from autowww — not the hub folder.
4) User said forge-lcdl or governed tasks? → always lcdl repo abbr.

## Using several at once

lcdl library is authoritative for package releases; LCDL-hub is a machine-local layout convenience.
Typical hub clones: fl, fc — may duplicate clones also present under Code/.

## Terms covered

- [**lcdl**](../terms/lcdl.md)
- [**LCDL-hub**](../terms/lcdl-hub.md)
- [**flw**](../terms/flw.md)
- [**fc**](../terms/fc.md)
- [**fl**](../terms/fl.md)

## Examples from chat / plan.md

"pip install -e ../forge-lcdl" from cockpit → Code/forge-lcdl, not ~/LCDL/.

Open LCDL.code-workspace with forge-composer taxonomy work → ~/LCDL/ hub; promote docs still target fc + composer-workbench.

---

*Bridge page `lcdl-repo-vs-lcdl-hub` — read when multiple abbreviations appear in one sentence.*
