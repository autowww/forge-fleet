# Fleet handbook UX audit — May 2026

**Scope:** Public Fleet handbook (`forge-fleet` Markdown → `forge-fleet-website` static build).  
**Intent:** Baseline before IA + shell refactor; aligns with [`docs/design/`](../design/) design contracts in-repo.

## Summary

| Dimension | Before (live / pre-refactor) | Target |
|-----------|------------------------------|--------|
| Global IA | Flat “Chapters” tree exposing every doc | Manifest-driven horizontal nav (`docs/site-nav.yaml`) + section sidebars |
| Maintainer visibility | Same rail as public content | **More** menu (Maintainers, Design hub, Changelog) |
| Home / Start | Dense README + short Start index | Hero + path cards; Start as human routing hub |
| Page length | Long mixed-topic pages | One job per page where feasible; hub pages for scan |
| Visual language | Mostly prose + tables | KS primitives + diagrams per [`VISUAL-COVERAGE.md`](VISUAL-COVERAGE.md) |

## Findings (_prioritized)_

1. **Navigation cognitive load** — Users saw every chapter at once; no task-based grouping at the top of the page. _Mitigation:_ top bar with dropdowns capped by `dropdown_max_items` in `site-nav.yaml`.
2. **Duplicate nav in DOM** — Mobile + desktop sidebars duplicate links; acceptable for a11y if labeled; avoid a third redundant block. _Mitigation:_ single sticky rail + offcanvas.
3. **Homepage positioning** — Technically correct opener without product framing. _Mitigation:_ Pack 03 hero + role table kept above fold; deeper detail unchanged lower on page.
4. **Examples discoverability** — Many siblings without grouping in the old rail. _Mitigation:_ Examples hub + Reference cross-links (Pack 07).

## Scorecard snapshot

Use [`docs/design/UX-SCORECARD.md`](../design/UX-SCORECARD.md) for weighted rubric. This audit records **directional** scores only:

- Information scent: **Medium → High** (after manifest + section sidebars).
- Task success (install / first job): **High** (existing Learn 101; copy tightening in Pack 04).
- Enterprise trust (Operate 301): **Medium → High** (tone + checklist links in Pack 06).

## Follow-ups

- Re-run this audit after each major pack; link deltas in `CHANGELOG.md` when user-visible.
- Keep [`UX-PAGE-INVENTORY.md`](UX-PAGE-INVENTORY.md) in sync with emitted HTML slugs.
