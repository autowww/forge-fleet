# Fleet content chunking concept

## Problem

The current Fleet site contains a lot of useful information, but too much of it is presented at once. Readers see many links, long tables, implementation details, and operational caveats before they know what to do next.

## Principle: one page, one job

Every page should answer one of these jobs:

- Explain a concept.
- Help a reader complete a task.
- Help a reader choose a path.
- Let a reader look up a contract.
- Help an operator recover from a problem.

If a page does two or more jobs, split it.

## Context budget

Every public page gets a small context block at the top. Do not repeat full system context everywhere.

```text
Goal: what the reader will do or understand
Audience: who this page is for
Time: rough time if task-based
Prerequisites: only what is required
Output: what should exist afterward
```

## Progressive disclosure

Use progressive disclosure for details that are useful but interrupt first-read flow.

- Use callouts for warnings and invariants.
- Use accordions/details for advanced variants.
- Use reference links for full API details.
- Use diagrams before long explanations.
- Use comparison tables only when a decision is needed.

## Visible information limits

- Maximum 6 path cards on a hub.
- Maximum 7 H2s on a non-reference page.
- Maximum 8 links in any visible link group.
- Maximum 5 troubleshooting symptoms in a beginner tutorial.
- Maximum 3 CTAs in a hero.

## Page splitting candidates

- Home: split implementation details into Reference and Operate pages.
- Examples: split by language/task, but group in one visual hub.
- Container templates: split beginner explanation, build guide, schema reference, and troubleshooting.
- Caddy/Granite: split conceptual topology from copy-paste config.
- Operate 301: separate production checklist, security, observability, backup, upgrades, and incident runbooks.
