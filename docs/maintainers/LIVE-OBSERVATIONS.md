# Live Fleet UX observations — 2026-05-17

Source reviewed: `https://fleet.forgesdlc.com/` and representative pages for Start, Learn 101, Build 201, Operate 301, and Reference. Comparison source: `https://forgesdlc.com/` and `https://forgesdlc.com/for-agents.html`. Local source context: uploaded `forge-fleet-2026-05-16T21-46-18.zip`.

## Current Fleet pattern

- The site starts with a long `Chapters` list before the article body. It exposes Build 201, Examples, Learn 101, Maintainers, Operate 301, Reference, Start, and Test Results as visible top-level link groups.
- The same long navigation block is rendered twice in the plain text extraction: once before the article and again before `Handbook`. This may be desktop + mobile chrome, but it still reflects excessive hidden/visible DOM and poor source order.
- The home page body starts as handbook prose, not a product landing page. The first description is technically accurate but dense: bearer-aware HTTP orchestrator, `docker_argv`, SQLite, `/v1/*`, `/admin/`.
- The homepage includes `Handbook journeys`, `API at a glance`, install commands, update semantics, versioning, submodules, telemetry, roadmap, and limitations. These are useful but mixed into one long page.
- The Start page is very short and mainly a routing table. It should become the main human routing hub.
- The Learn/Build/Operate hubs exist, but they read like generated indexes rather than guided learning/product surfaces.
- Maintainer pages are visible in primary navigation; they should be moved under a lower-priority More/Internal menu so public users are not distracted.
- Examples are over-exposed as many sibling pages in the global nav. They should be grouped into task buckets.

## What ForgeSDLC does better

- Top navigation is grouped by user intent: Why Forge, How It Works, Who It's For, Adopt & Lead, For Agents, Blog, Principles.
- The homepage has a real hero, clear tagline, short value proposition, and calls to action before long content.
- Sections use benefit-oriented headings: Why now, How Forge works, What teams actually get, Built for every layer, Beyond traditional frameworks, Built for agents.
- For Agents provides a compact map for machines and humans while still using ordinary Markdown.

## Target transformation

Move Fleet from a generated handbook index to a product-grade documentation experience:

1. Horizontal top nav with dropdowns, no giant always-visible chapter list.
2. Page-local expandable vertical nav, only current section expanded, fits one screen.
3. Hero sections for Home, Start, Learn 101, Build 201, Operate 301, Reference, Examples.
4. Short pages with progressive disclosure and task-based routing.
5. Rich KS components for cards, callouts, diagrams, code panels, tabs, FAQs, and route cards.
6. Human-facing prose first, exact API/reference detail second.
7. Public docs separated from Maintainer docs.
8. CI gates for link health, page length, nav size, accessibility landmarks, and deployment smoke.
