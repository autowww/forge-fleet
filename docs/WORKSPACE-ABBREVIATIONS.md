# Workspace abbreviations glossary

Machine-readable catalog of Forge workspace abbreviations, lifecycle shorthand,
discipline codes, and disambiguation bridges. Canonical human prose lives in
docs/WORKSPACE-ABBREVIATIONS.md and blueprints/sdlc/methodologies/forge/WORKSPACE-ABBREVIATIONS.md.
Repo folders are under ~/Code/ unless noted; handbook shells deploy to Firebase Hosting.


**Canonical catalog:** `docs/workspace-abbreviations/catalog.yaml` — run `python3 scripts/generate-workspace-abbreviations.py`, then `./sync-workspace-abbreviations.sh`.

**Published on the web:**

| Surface | URL (after deploy) |
|---------|-------------------|
| ForgeSDLC knowledge | [forgesdlc.com — workspace abbreviations](https://forgesdlc.com/workspace-abbreviations.html) |
| Blueprints handbook (hub) | [blueprints.forgesdlc.com — workspace abbreviations](https://blueprints.forgesdlc.com/sdlc--methodologies-forge-workspace-abbreviations.html) |
| Term pages | `…/workspace-abbreviations/terms/<abbr>.html` on blueprints.forgesdlc.com |
| Local workspace handbook | `workspace-handbook/abbreviations.html` |

**Last updated:** 2026-07-01

---

## Quick index by category

### Artifact

| Abbr | Summary | Term page |
|------|---------|-----------|
| **DEF** | Defect folder prefix DEF-NNNN — registry at docs/defects/INDEX.md with defect.md, rca.md, test-impact.md. | [open](workspace-abbreviations/terms/def.md) |
| **P1** | Validate that a problem is worth solving — audience evidence, Ore intake, distinct from SDLC discover ordering. | [open](workspace-abbreviations/terms/p1.md) |
| **P2** | Solution fit experiments, prototypes, evidence for whether the approach works before heavy commit. | [open](workspace-abbreviations/terms/p2.md) |
| **P3** | Funding, metrics, roadmap, GTM — handoff into SDLC as the embedded build engine. | [open](workspace-abbreviations/terms/p3.md) |
| **P4** | Go-to-market execution — standard product "launch" language distinct from SDLC Release (F). | [open](workspace-abbreviations/terms/p4.md) |
| **P5** | Post-launch growth, adoption metrics, feedback loops — operations signal re-enters as Ore. | [open](workspace-abbreviations/terms/p5.md) |
| **P6** | End-of-life planning, deprecation, migration — dual-track overlap and retirement obligations in PDLC.md. | [open](workspace-abbreviations/terms/p6.md) |
| **SDLC-phases** | Internal shorthand A–F for delivery phases; reader-facing names are Discover/Prioritize through Release. | [open](workspace-abbreviations/terms/sdlc-phases.md) |

### Ba Ka

| Abbr | Summary | Term page |
|------|---------|-----------|
| **BAPM** | BABOK knowledge area for planning BA work, stakeholder engagement, and performance measurement. | [open](workspace-abbreviations/terms/bapm.md) |
| **EC** | Interviews, workshops, observation, prototyping to draw out requirements and build consensus. | [open](workspace-abbreviations/terms/ec.md) |
| **RADD** | Specify and model requirements — user stories, use cases, NFRs, data and process models. | [open](workspace-abbreviations/terms/radd.md) |
| **RLCM** | Trace, maintain, prioritize, and assess requirements changes from birth to retirement. | [open](workspace-abbreviations/terms/rlcm.md) |
| **SA** | Current state, future state, risks, business case — SWOT, PESTLE, feasibility in techniques matrix. | [open](workspace-abbreviations/terms/sa.md) |

### Cursor Plan

| Abbr | Summary | Term page |
|------|---------|-----------|
| **L** | Large request — ~100k–400k token order; cross-cutting or multi-surface within ecosystem. | [open](workspace-abbreviations/terms/l.md) |
| **M** | Medium request — ~25k–100k token order; multi-file feature within one repo boundary. | [open](workspace-abbreviations/terms/m.md) |
| **S** | Small request — ~5k–25k token order; focused edit in one module or doc section. | [open](workspace-abbreviations/terms/s.md) |
| **XL** | Extra-large — >400k token order; multi-repo program, long-running loops, broad refactors. | [open](workspace-abbreviations/terms/xl.md) |
| **XS** | Extra-small agent request — heuristic <5k tokens; inline work, no heavy orchestration. | [open](workspace-abbreviations/terms/xs.md) |
| **subagent** | Specialized child agent (explore, shell, bugbot, etc.) launched via Task tool for bounded parallel work. | [open](workspace-abbreviations/terms/subagent.md) |

### Discipline

| Abbr | Summary | Term page |
|------|---------|-----------|
| **ARCH** | Structure, quality attributes, maintainability — ARCH-SDLC-PDLC-BRIDGE.md and ADR practice. | [open](workspace-abbreviations/terms/arch.md) |
| **BA** | Stakeholder needs, requirements, solution fit — bridge file BA-SDLC-PDLC-BRIDGE.md in bp. | [open](workspace-abbreviations/terms/ba.md) |
| **CS** | User outcomes, onboarding, support loops — CS-SDLC-PDLC-BRIDGE.md, versona-cs.mdc. | [open](workspace-abbreviations/terms/cs.md) |
| **DEVOPS** | Delivery, operations, production reliability — DEVOPS-SDLC-PDLC-BRIDGE.md, versona-devops.mdc. | [open](workspace-abbreviations/terms/devops.md) |
| **PM** | Delivery feasibility within scope, time, cost, risk — PM-SDLC-PDLC-BRIDGE.md governance lens. | [open](workspace-abbreviations/terms/pm.md) |
| **SE** | Craft, CS fundamentals, code-level quality — SE-SDLC-PDLC-BRIDGE.md and versona-se.mdc. | [open](workspace-abbreviations/terms/se.md) |
| **SEC** | Defenses against attacks and systemic failures — SEC-SDLC-PDLC-BRIDGE.md, versona-security.mdc. | [open](workspace-abbreviations/terms/sec.md) |
| **TEST** | Quality evidence, test design, regression safety — TESTING-SDLC-PDLC-BRIDGE.md (filename), abbr TEST in chat. | [open](workspace-abbreviations/terms/test.md) |
| **UX** | Usability, desirability, accessibility, consistency — UX-SDLC-PDLC-BRIDGE.md and versona-ux.mdc. | [open](workspace-abbreviations/terms/ux.md) |
| **Versona** | Bounded discipline reviewer with optional §5 structured concern report — templates in bp versona/catalog/. | [open](workspace-abbreviations/terms/versona.md) |

### Handbook Shell

| Abbr | Summary | Term page |
|------|---------|-----------|
| **bpw** | Public static handbook generator for blueprints.forgesdlc.com — consumes bp and ks submodules. | [open](workspace-abbreviations/terms/bpw.md) |
| **ffw** | Private handbook deploy for Fleet — forge-fleet submodule + kitchensink → Firebase fleet-2f1d3. | [open](workspace-abbreviations/terms/ffw.md) |
| **flsw** | Private Firebase deploy shell for the Lenses handbook — submodules forge-lenses + kitchensink. | [open](workspace-abbreviations/terms/flsw.md) |
| **flw** | Private handbook deploy for LCDL — forge-lcdl submodule + kitchensink → Firebase lcdl-542d8. | [open](workspace-abbreviations/terms/flw.md) |
| **fpw** | Private handbook deploy for Platform — forge-platform submodule + kitchensink → forge-platform-1541d. | [open](workspace-abbreviations/terms/fpw.md) |

### Hub

| Abbr | Summary | Term page |
|------|---------|-----------|
| **Code-hub** | Primary Forge multi-repo workspace at ~/Code/ — each subfolder is its own git history. | [open](workspace-abbreviations/terms/code-hub.md) |
| **LCDL-hub** | Independent multi-repo folder ~/LCDL/ on the home directory — not forge-lcdl/ under Code/. | [open](workspace-abbreviations/terms/lcdl-hub.md) |

### Lifecycle

| Abbr | Summary | Term page |
|------|---------|-----------|
| **ADR** | Dated decision log capturing context, decision, and consequences — common in fp and product repos. | [open](workspace-abbreviations/terms/adr.md) |
| **DoD** | Exit criteria proving a work item or phase is complete — evidence-based, not narrative-only. | [open](workspace-abbreviations/terms/dod.md) |
| **DoR** | Entry criteria before work starts — e.g. Roadmap DoR before WBS, story DoR before sprint commit. | [open](workspace-abbreviations/terms/dor.md) |
| **Forge-Spark** | Smallest delivery unit (~1–4h task), phase-prefixed discover:/specify:/…; maps to WBS Task. | [open](workspace-abbreviations/terms/forge-spark.md) |
| **IPE** | Compact phase view in PRODUCT-DELIVERY-FORGE-IPE.md — industry + Forge + IPE per lifecycle phase. | [open](workspace-abbreviations/terms/ipe.md) |
| **MVP** | Smallest product slice that tests core value hypothesis — a Product Spark category. | [open](workspace-abbreviations/terms/mvp.md) |
| **PDCA** | Remediation loop — define acceptance, implement, check, act until green; used in Forge Cursor planning. | [open](workspace-abbreviations/terms/pdca.md) |
| **PDLC** | Product phases P1–P6 from problem discovery through sunset — building the right product. | [open](workspace-abbreviations/terms/pdlc.md) |
| **PoC** | Time-boxed validation slice — often packaged as a Product Spark type, not a Forge Spark task label. | [open](workspace-abbreviations/terms/poc.md) |
| **Product-Spark** | Potentially shippable product slice — PoC, MVP, or phased increment; aliases release slice, product increment. | [open](workspace-abbreviations/terms/product-spark.md) |
| **RCA** | Systematic investigation of underlying defect cause — paired with test impact in Forge defect workflow. | [open](workspace-abbreviations/terms/rca.md) |
| **SDLC** | Delivery phases Discover/Prioritize → Specify → Design → Build → Verify → Release; letters A–F in bridges. | [open](workspace-abbreviations/terms/sdlc.md) |
| **WBS** | Hierarchical decomposition Theme → Epic → Story → Task; Task maps to Forge Spark when IDs align. | [open](workspace-abbreviations/terms/wbs.md) |

### Localization

| Abbr | Summary | Term page |
|------|---------|-----------|
| **L10N** | Engineering workflow for locale assets, SKU list governance, and sync-workspace-localization-scope.sh. | [open](workspace-abbreviations/terms/l10n.md) |
| **RTL** | RTL locale support for he/he-IL and ar per WORKSPACE-LOCALIZATION-SCOPE — mirroring, bidi, QA pass. | [open](workspace-abbreviations/terms/rtl.md) |
| **i18n** | Designing for multiple locales before translation — string externalization, plural rules, layout flex. | [open](workspace-abbreviations/terms/i18n.md) |

### Platform

| Abbr | Summary | Term page |
|------|---------|-----------|
| **ADK** | Optional runtime/orchestration layer — orientation only; does not replace Forge work model or WBS. | [open](workspace-abbreviations/terms/adk.md) |
| **EML** | On-disk mail export from OWA Downloads adopt path — Message-ID identity, Cockpit manifest renames. | [open](workspace-abbreviations/terms/eml.md) |
| **FTS** | SQLite FTS indices for local search — Lenses .lenses-local/, Cockpit message headers, KA deck index. | [open](workspace-abbreviations/terms/fts.md) |
| **MCP** | MCP servers expose tools/resources to agents — Cursor MCP file system, fccmem MCP feed adapter. | [open](workspace-abbreviations/terms/mcp.md) |
| **OWA** | Browser Outlook UI harvested via Edge CDP — search-day tier, EML export, DOM list strategies. | [open](workspace-abbreviations/terms/owa.md) |
| **PAT** | GitHub PAT for Lenses .lenses-repo/<login>/ overlays and private git+ssh clone auth contexts. | [open](workspace-abbreviations/terms/pat.md) |
| **fllm** | Informal shorthand for on-device / local LLM worker paths — not a separate git repo abbreviation. | [open](workspace-abbreviations/terms/fllm.md) |

### Repo

| Abbr | Summary | Term page |
|------|---------|-----------|
| **a11y** | Accessibility checking utilities and automation — private repo with bp + ks submodules. | [open](workspace-abbreviations/terms/a11y.md) |
| **aw3** | Legacy AutoWWW / Irrida glossary — outside Forge handbook deploy scope; reference only. | [open](workspace-abbreviations/terms/aw3.md) |
| **bp** | Reusable SDLC/PDLC process framework and discipline bridges — the methodology | [open](workspace-abbreviations/terms/bp.md) |
| **cdp** | CDP control plane — surface leases, browser session registry, HTTP API for attach owners (typical :18770). | [open](workspace-abbreviations/terms/cdp.md) |
| **cert** | Bank health / certificator REST UI — typical dev port 11350, integrates with Fleet for git-self-update. | [open](workspace-abbreviations/terms/cert.md) |
| **cockpit** | M365/Teams ingest dashboard — Electron studio + Python cockpit_server; primary laptop runner. | [open](workspace-abbreviations/terms/cockpit.md) |
| **cyn** | Android app Situ8 — Google Sign-In, predefined LLM prompts (OpenAI, Gemini). Package com.situ8.app. | [open](workspace-abbreviations/terms/cyn.md) |
| **fa** | Markdown → handbook HTML builder shipped inside ks at forge-autodoc/ — not a separate submodule. | [open](workspace-abbreviations/terms/fa.md) |
| **fa-acc-leo** | forge-accessibility — CDP + axe audits, Python + Electron; primary clone forge-accessibility-leo/. | [open](workspace-abbreviations/terms/fa-acc-leo.md) |
| **fa-acc-vika** | Optional second local clone of autowww/forge-accessibility with folder suffix vika4ka. | [open](workspace-abbreviations/terms/fa-acc-vika.md) |
| **fc** | Deploy manifests into sibling repos plus taxonomy ETL/refine for artifact JSON — clone beside consumers. | [open](workspace-abbreviations/terms/fc.md) |
| **fccm** | Private Android pulse app (Expo) — read-only PulseEvent feed from Fleet memory; Cockpit MVP aromas slice. | [open](workspace-abbreviations/terms/fccm.md) |
| **fccmem** | Fleet remote memory client — PulseEvent payloads, API and MCP ingest/feed adapters for Cockpit aromas. | [open](workspace-abbreviations/terms/fccmem.md) |
| **fccw** | Spoken/file alias for cockpit — same repo as forge-cockpit-web/. | [open](workspace-abbreviations/terms/fccw.md) |
| **ff** | HTTP bearer orchestrator for Docker-argv jobs — SQLite job store, admin UI, git-self-update endpoint. | [open](workspace-abbreviations/terms/ff.md) |
| **fka** | Local case-study knowledge assistant — SharePoint sync, LCDL atoms, SQLite+FTS, Granite copilot RAG. | [open](workspace-abbreviations/terms/fka.md) |
| **fl** | Local-first workspace control plane — lenses Python package, Studio on /studio/, Classic dashboard on :8080. | [open](workspace-abbreviations/terms/fl.md) |
| **forge** | Public methodology product site at forgesdlc.com — encyclopedic knowledge and tutorials. | [open](workspace-abbreviations/terms/forge.md) |
| **fp** | Platform schemas, ADRs, ForgeRun/AgentRun contracts, workcell references — ecosystem architecture source. | [open](workspace-abbreviations/terms/fp.md) |
| **fwc** | Private workcell runners — local_llm_worker, pack loader; domain micro-packs stay in ks. | [open](workspace-abbreviations/terms/fwc.md) |
| **ks** | Shared design system — CSS themes, Python UI components, SVG templates, forge-autodoc, UX auditor tooling. | [open](workspace-abbreviations/terms/ks.md) |
| **lcdl** | Private Python library for governed synchronous LLM tasks, operators, and OpenAI-compatible transport. | [open](workspace-abbreviations/terms/lcdl.md) |
| **s8w** | Marketing site generator for situ8.app / www.situ8.app — Python + Markdown + kitchensink submodule. | [open](workspace-abbreviations/terms/s8w.md) |

### Ux Governance

| Abbr | Summary | Term page |
|------|---------|-----------|
| **det** | KS website UX auditor deterministic checks (DET.* rule ids) — repeatable layout/hash/nav enforcement. | [open](workspace-abbreviations/terms/det.md) |
| **hash** | Three-letter visual catalog id on emitted HTML — hash="Xyz" and data-ks-hash="Xyz" globally unique. | [open](workspace-abbreviations/terms/hash.md) |

## Disambiguation bridges

Read these when a message mixes terms that sound alike:

- [Product repo ↔ handbook deploy shell](workspace-abbreviations/bridges/handbook-deploy-pairs.md)
- [forge-lcdl library vs ~/LCDL/ hub](workspace-abbreviations/bridges/lcdl-repo-vs-lcdl-hub.md)
- [Product Spark vs Forge Spark](workspace-abbreviations/bridges/product-spark-vs-forge-spark.md)
- [forge-a11y-checker vs Forge A11y Studio](workspace-abbreviations/bridges/a11y-checker-vs-a11y-studio.md)
- [Forge control-plane stack](workspace-abbreviations/bridges/control-plane-stack.md)
- [Kitchen Sink consumer chain](workspace-abbreviations/bridges/ks-consumer-chain.md)
- [Cursor plan-chat vocabulary](workspace-abbreviations/bridges/plan-chat-vocabulary.md)
- [Cockpit + CDP + Edge + OWA stack](workspace-abbreviations/bridges/cockpit-cdp-edge.md)

## Related glossaries (domain vocabulary, not repo shorthand)

- [Forge naming reference](https://blueprints.forgesdlc.com/sdlc--methodologies-forge-naming-reference.html) — Ore, Spark, Charge, Versona
- [Forge Platform glossary](https://platform.forgesdlc.com/docs/glossary.html) — ForgeRun, workcells
- [Forge Lenses glossary](https://blueprints.forgesdlc.com/lenses/guides/21-glossary.html) — Studio, Wizard
