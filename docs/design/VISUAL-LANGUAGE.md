# Fleet handbook visual language

This file complements **[`KS-COMPONENTS-CONCEPT.md`](KS-COMPONENTS-CONCEPT.md)** with **Fleet-specific** guidance for authors and maintainers.

## Principles

1. **Human headline, machine detail second** — Open with a sentence a new integrator would say out loud; tuck route tables and env matrices below the fold.
2. **One visual idea per figure** — Prefer a second short diagram over one crowded canvas.
3. **KS-native diagrams** — Use `blueprint-diagram-ascii` fences from forge-autodoc with mandatory **`alt:`** and **`caption:`** lines (see **[`VISUAL-COVERAGE.md`](../maintainers/VISUAL-COVERAGE.md)**).
4. **No net-new Mermaid** in Fleet handbook Markdown (workspace publishing rule). Exception: Kitchen Sink showcase museum only.

## Layout surfaces

| Surface | Role |
|---------|------|
| Horizontal **`site-nav.yaml`** buckets | Task-based IA; Maintainers stay under **More** |
| Section sidebar | Current chapter only; collapsible groups from forge-autodoc |
| Right-rail ToC | Anchors from page headings (`extract_toc_from_html`) |

## Tone by tier

| Tier | Voice |
|------|--------|
| Learn 101 | Instructor — short steps, explicit verification |
| Build 201 | Pair-programmer — recipes, copy-paste guarded |
| Operate 301 | Staff engineer — checklists, explicit risk |
| Reference | Spec — tables, monospace, minimal narrative |

## Accessibility

- Every diagram fence carries **`alt:`** describing the outcome, not the drawing style.
- Keep heading order strict (`h1` once via template, then `h2`/`h3`) so the ToC rail stays meaningful.

## When to update coverage

Touch **[`VISUAL-COVERAGE.md`](../maintainers/VISUAL-COVERAGE.md)** whenever you add or retire a diagram on a **medium/large** page.
