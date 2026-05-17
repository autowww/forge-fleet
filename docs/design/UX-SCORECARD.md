# Fleet website UX scorecard — current state and target

Date: 2026-05-17  
Scope: live `fleet.forgesdlc.com` documentation UX, not API implementation correctness.

## Executive score

**Current UX score: 48 / 100**

Fleet has useful content and a reasonable 101/201/301 source structure, but the live site still feels like a generated handbook. A human visitor is confronted with a long chapter list, duplicated nav chrome, dense technical descriptions, too many visible links, and limited visual hierarchy before they know what Fleet is or where to start.

**Target UX score after this refactor: 86 / 100**

The target is not flashy marketing. It is a clean enterprise documentation surface where a human can choose a path, read short pages, understand context quickly, and then drill into exact contracts when needed.

## Category scoring

| Category | Current | Target | Notes |
|---|---:|---:|---|
| First impression / hero clarity | 4 | 9 | Current homepage starts as README/handbook prose. Needs product hero, CTA, value prop, architecture snapshot. |
| Global navigation | 3 | 9 | Current visible chapter list is too long and includes Maintainers. Needs horizontal nav with dropdowns and grouped intent. |
| Local navigation | 4 | 9 | Current `On this page` is useful but appears after content and global nav is overwhelming. Needs compact vertical section nav plus right rail. |
| Information architecture | 6 | 9 | Source IA is improved, but live navigation does not make it feel curated. |
| Content chunking | 5 | 9 | Pages mix setup, API, operations, limitations, and roadmap. Need one job per page. |
| Tutorial readability | 6 | 9 | Learn pages have outcome/audience/time blocks, which is good. Need stronger step/verify/troubleshoot pattern. |
| Examples findability | 4 | 8 | Many examples are visible as global siblings. Need grouped recipes and copy-paste cards. |
| Visual explanation | 3 | 8 | Current visuals are sparse/ASCII. Need KS diagrams and cards. |
| Enterprise confidence | 5 | 8 | Content exists but should look curated, version-aware, and runbook-driven. |
| Accessibility / responsive navigation | 5 | 8 | Cannot fully verify visually here; target requires keyboard/ARIA/dropdown/mobile tests. |
| Public/internal separation | 4 | 9 | Maintainer pages are too prominent. |
| Source-to-site governance | 6 | 8 | Existing docs checks are good; add UX-specific checks. |

## Hard UX acceptance gates

- Home page communicates what Fleet is and where to go next within the first viewport.
- No public page shows more than 7 primary top-nav items.
- No dropdown shows more than 8 visible items without grouping.
- Maintainers are not a primary top-level item; they live under `More` or `/maintainers/` with an internal label.
- Top-level pages have hero + path cards + at most one screen of local navigation.
- Article pages have no more than 7 H2 sections unless they are Reference pages.
- Hubs are under 900 words; task tutorials are split when they exceed 1200 words or 9 H2s.
- Every tutorial has: Goal, Audience, Time, Prerequisites, Steps, Verify, Troubleshoot, Next.
- Every complex concept has a visual: KS diagram, card flow, comparison table, or callout.
- Keyboard users can open dropdowns, expand local nav, and reach the article content without crossing a huge link dump.
