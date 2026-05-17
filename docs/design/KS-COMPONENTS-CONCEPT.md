# Kitchen Sink component usage concept for Fleet docs

Fleet should use Kitchen Sink (`ks`) as a design-system layer, not only as a vendored submodule.

## Layouts

Use these KS layouts where available:

| Page type | KS layout |
|---|---|
| Home | `landing_page` or `product_page` |
| Section hubs | `product_page`, `split_page`, or `handbook_page` with custom hero |
| Tutorials | `handbook_page` with compact left nav and right rail ToC |
| Reference | `handbook_page` plus route/schema components |
| Examples | `listing_page` or card grid inside `handbook_page` |

## Components

Use these component families:

| Need | Component/pattern |
|---|---|
| Product hero | `render_product_landing_hero` |
| Page header | `render_page_header`, `render_page_header_chapter` |
| Path cards | `render_card_rail`, `render_rail`, card grid classes |
| Tier navigation | `render_tier_nav` |
| ToC | `render_toc_sidebar`, `render_toc_sidebar_simple` |
| Warnings | `render_alert` / Forge callout classes |
| Cross-links | `render_cross_refs`, `render_nav_buttons` |
| API tables | `render_table`, `render_io_table` |
| Stats | `render_marketing_stat_band` |
| FAQs | `render_faq_section` |
| Tabs | `render_tab_panel` |
| Diagrams | `render_ks_diagram_block`, `blueprint-diagram`, `blueprint-diagram-ascii` fences |

## Diagram requirements

Add at least these diagrams:

1. Fleet in the Forge ecosystem: Studio/Lenses -> Fleet -> Docker -> SQLite -> Admin.
2. First job lifecycle: POST job -> run -> persist -> poll -> inspect.
3. Workspace upload: create job -> upload tarball -> localize path -> run container.
4. Template build: requirement -> template -> BuildKit -> image -> job.
5. Caddy/TLS topology: public host -> Caddy -> Fleet and adjacent services.
6. Operate trust boundaries: browser/client, reverse proxy, Fleet, Docker socket, filesystem.
7. Backup/restore path: stop/snapshot/copy/verify/restart.
8. Self-update flow: dev clone -> push -> remote self-update endpoint -> systemd restart -> verify.

## Rich component rules

- A diagram must have meaningful alt text and caption.
- Code blocks should be copy-paste runnable and followed by expected output.
- Callouts should be concise and not used as paragraphs with borders.
- Cards should have action labels, not just titles.
- Do not use visuals to hide missing content; visuals must clarify actual workflows.
