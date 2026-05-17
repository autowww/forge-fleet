# Fleet navigation concept

## Goal

Make Fleet navigable by intent, not by source folder. A first-time human should see a small number of choices and understand which one fits their task.

## Horizontal top navigation

Use a single sticky horizontal nav for desktop. Use the same IA in a mobile drawer.

```text
Fleet
  Home
  Start
  Learn
  Build
  Operate
  Reference
  Examples
  More
```

### Dropdown model

Each top item opens a dropdown with at most 5-8 curated links. Avoid dumping every page into the dropdown.

```text
Start
  Choose your path
  10-minute local quickstart
  Studio/Lenses setup
  API client path
  Host operator path

Learn
  What is Fleet?
  Install locally
  Your first job
  Admin dashboard tour
  Connect Studio/Lenses

Build
  Jobs API guide
  Workspace upload
  Requirement templates
  Caddy/TLS front door
  Integration recipes

Operate
  Production checklist
  Security model
  Observability and SLOs
  Backup and restore
  Upgrade and rollback
  Incident runbooks

Reference
  HTTP API
  OpenAPI
  JSON Schemas
  Environment variables
  Error model

Examples
  curl
  Python
  TypeScript/fetch
  CI smoke
  Lenses/Studio

More
  Changelog
  Architecture
  Troubleshooting
  Maintainers
```

## Navigation rules

- Never expose generated file order as primary navigation.
- Never show Maintainers as a first-class public path.
- Keep global nav stable across pages.
- Keep dropdown labels action-oriented.
- Use one source-of-truth nav manifest, for example `docs/site-nav.yaml`.
- Generate both desktop and mobile nav from the same manifest.
- Mark active section and active page.
- Include `Skip to content` before navigation.
- Ensure ARIA attributes for dropdowns and disclosure controls.

## Fit-one-screen local nav

Inside a section page, show a compact vertical nav. Only one section is expanded. Current section is open by default; siblings are collapsed.

```text
Learn 101
  ▾ Getting started
    What is Fleet?
    Install locally
    First job
  ▸ Studio connection
  ▸ Admin dashboard
  ▸ Troubleshooting basics
```

Target: local navigation occupies no more than one viewport on a 13-inch laptop.
