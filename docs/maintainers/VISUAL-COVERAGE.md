# Handbook visual coverage map

Fleet handbook Markdown avoids net-new **Mermaid** per workspace publishing rules. We use **Kitchen Sink–backed `blueprint-diagram-ascii` fences** (see forge-autodoc), **tables**, and curated **PNG** screenshots (**`/admin/`**).

| Public page | Diagram / visual | KS key or asset | Status |
|-------------|------------------|-----------------|--------|
| *(Site chrome)* | Sticky horizontal IA + section rail | `docs/site-nav.yaml` + forge-autodoc | Implemented |
| [`docs/start/01-start-here.md`](../start/01-start-here.md) | Numbered flow + diagram slot | Text (KS pending for overview figure) | Partial |
| [`docs/learn-101/01-what-is-fleet.md`](../learn-101/01-what-is-fleet.md) | Mental model | `linear` ASCII fence | Implemented |
| [`docs/learn-101/06-first-fleet-job.md`](../learn-101/06-first-fleet-job.md) | Job lifecycle | `state` ASCII fence | Implemented |
| [`docs/build-201/01-workspace-upload.md`](../build-201/01-workspace-upload.md) | Workspace staging | `sequence` ASCII fence | Implemented |
| [`docs/build-201/02-container-templates.md`](../build-201/02-container-templates.md) | Template path | `gate` ASCII fence | Implemented |
| [`docs/build-201/03-caddy-systemd.md`](../build-201/03-caddy-systemd.md) | TLS topology | `network` ASCII fence | Implemented |
| [`docs/operate-301/01-security.md`](../operate-301/01-security.md) | Trust boundary | `network` ASCII fence | Implemented |
| [`docs/operate-301/03-architecture.md`](../operate-301/03-architecture.md) | Dispatch overview | `linear` ASCII fence | Implemented |
| [`docs/operate-301/05-upgrade-release-and-remote-update.md`](../operate-301/05-upgrade-release-and-remote-update.md) | Upgrade vs remote update | `linear` ASCII fence | Implemented |
| [`docs/learn-101/07-admin-dashboard-and-studio.md`](../learn-101/07-admin-dashboard-and-studio.md) | PNG screenshot | `../assets/admin-overview.png` | Refresh when UI drift |

**Accessibility:** every `blueprint-diagram-ascii` block includes **`alt:`** and **`caption:`** lines. Prefer short nearby prose explaining the figure.

Update this map whenever a **medium/large** page grows visuals or when forge-autodoc diagram keys change.
