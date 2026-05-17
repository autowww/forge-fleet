# Fleet documentation IA map — target

## Public tree

```text
/
  Home
/start/
  Choose your path
  Local quickstart
  Studio/Lenses path
  API integrator path
  Host operator path
/learn/
  What is Fleet?
  Install locally
  First job
  Admin dashboard tour
  Connect Studio/Lenses
  Beginner troubleshooting
/build/
  Jobs API guide
  Workspace upload
  Requirement templates
  Container types and managed services
  Caddy/TLS front door
  Integration recipes
/operate/
  Production checklist
  Security model
  Observability and SLOs
  Backup and restore
  Upgrade and rollback
  Incident runbooks
/reference/
  HTTP API
  OpenAPI
  JSON Schemas
  Environment variables
  Error model
  CLI and scripts
/examples/
  curl
  Python
  TypeScript/fetch
  CI smoke
  Lenses/Studio
  Workspace upload
  Caddy/TLS
/more/
  Changelog
  Architecture
  Troubleshooting
  Maintainers
```

## Hidden or lower-priority tree

```text
/maintainers/
  Site build notes
  Docs contracts and CI
  Visual coverage
  Screenshot workflow
  Prompt packs
```

## URL strategy

Prefer short human URLs:

```text
/start.html
/learn.html
/learn/what-is-fleet.html
/build/jobs-api.html
/operate/security.html
/reference/http-api.html
/examples/python.html
```

If the current generator flattens paths, preserve compatibility with redirects or canonical links:

```text
docs-learn-101-01-what-is-fleet.html -> /learn/what-is-fleet.html
```

## Source strategy

The source files can remain in `docs/learn-101/`, `docs/build-201/`, etc., but the site should be generated from a navigation manifest rather than filesystem order.

Recommended manifest:

```yaml
primary:
  - id: home
    label: Home
    href: index.html
  - id: start
    label: Start
    href: start.html
    dropdown:
      - label: Choose your path
        href: start.html
      - label: 10-minute local quickstart
        href: start/local-quickstart.html
sections:
  learn:
    label: Learn 101
    items:
      - label: What is Fleet?
        href: learn/what-is-fleet.html
        order: 10
        summary: Product mental model and where Fleet fits.
```
