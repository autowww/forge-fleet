---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "Product repo ↔ handbook deploy shell"
description: "Private handbook pairs share one pattern — product Markdown in the * repo,
Firebase deploy wiring in the *w shell with kitchensink + product submodules.
"
term_category: bridge
---

# Product repo ↔ handbook deploy shell

Private handbook pairs share one pattern — product Markdown in the * repo,
Firebase deploy wiring in the *w shell with kitchensink + product submodules.


## The collision

Engineers edit the wrong tree (flsw instead of fl), or deploy without bumping the
product submodule pointer — handbook shows stale docs.

## How to choose

1) Is the change product documentation or API behavior? → edit ff, lcdl, fl, fp, fi, or sti.
2) Is the change only Firebase/hosting/generator wiring? → edit ffw, flw, flsw, fpw, fiw, or stiw.
3) Ready to publish? → bump submodule in *w, build generator, deploy-websites.sh --only <shell>.
4) Did kitchensink CSS/components change too? → propagate ks first (sync-kitchensink-and-rebuild.sh).

## Using several at once

ff+ffw (fleet-2f1d3), lcdl+flw (lcdl-542d8), fl+flsw (lenses-d0fdb), fp+fpw (forge-platform-1541d),
fi+fiw (forge-intelligence-handbook, intelligence.forgesdlc.com), sti+stiw (sti-PLACEHOLDER).
Each shell submodules kitchensink/ and the matching product repo.

## Terms covered

- [**ff**](../terms/ff.md)
- [**ffw**](../terms/ffw.md)
- [**lcdl**](../terms/lcdl.md)
- [**flw**](../terms/flw.md)
- [**fl**](../terms/fl.md)
- [**flsw**](../terms/flsw.md)
- [**fp**](../terms/fp.md)
- [**fpw**](../terms/fpw.md)
- [**fi**](../terms/fi.md)
- [**fiw**](../terms/fiw.md)
- [**ks**](../terms/ks.md)

## Examples from chat / plan.md

LCDL task operator docs changed in forge-lcdl/docs → commit lcdl → cd flw →
git submodule update --remote forge-lcdl → build-site.py → ./deploy-websites.sh --only forge-lcdl-website

Fleet admin API doc fix in forge-fleet/ → separate commit in ffw bumping forge-fleet submodule only after ff push.

---

*Bridge page `handbook-deploy-pairs` — read when multiple abbreviations appear in one sentence.*
