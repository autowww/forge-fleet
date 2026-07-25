---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "forge-a11y-checker vs Forge A11y Studio"
description: "a11y is automation/checker utilities; fa-acc-leo is the full CDP+axe Electron Studio
(forge-accessibility). fa-acc-vika is an optional second clone of the same remote.
"
term_category: bridge
---

# forge-a11y-checker vs Forge A11y Studio

a11y is automation/checker utilities; fa-acc-leo is the full CDP+axe Electron Studio
(forge-accessibility). fa-acc-vika is an optional second clone of the same remote.


## The collision

User says "a11y" or "forge-accessibility" — agent edits checker scripts when Studio UI
is intended, or confuses fa (forge-autodoc) with accessibility repos.

## How to choose

1) Checker utilities, bp/ks submodule repo, batch automation? → a11y (forge-a11y-checker).
2) Studio UI, a11y-transcript CLI, CDP audits, Electron? → fa-acc-leo default.
3) User said vika4ka? → fa-acc-vika path explicitly.
4) Handbook HTML builder? → fa inside ks — unrelated to accessibility products.

## Using several at once

Both may use cdp manager and ks design patterns; only Studio is the interactive product for auditors.

## Terms covered

- [**a11y**](../terms/a11y.md)
- [**fa-acc-leo**](../terms/fa-acc-leo.md)
- [**fa-acc-vika**](../terms/fa-acc-vika.md)
- [**fa**](../terms/fa.md)
- [**cdp**](../terms/cdp.md)
- [**ks**](../terms/ks.md)

## Examples from chat / plan.md

"Run axe on staging in the Studio" → fa-acc-leo, port 8765 collision awareness with cockpit 9775.

"Add checker script for WCAG rule batch" → a11y repo; bump bp/ks submodules separately if process docs change.

---

*Bridge page `a11y-checker-vs-a11y-studio` — read when multiple abbreviations appear in one sentence.*
