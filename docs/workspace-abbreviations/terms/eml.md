---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "EML — Email message (.eml) artifact"
description: "On-disk mail export from OWA Downloads adopt path — Message-ID identity, Cockpit manifest renames.
"
term_abbr: "EML"
term_category: "platform"
---

# EML — Email message (.eml) artifact

On-disk mail export from OWA Downloads adopt path — Message-ID identity, Cockpit manifest renames.


## What it is

lcdl wait_for_stable_eml_in_downloads; cockpit eml_paths.py, cockpit_data_manifest v004 upgrades.

## When people say this

When planning dual-architecture Outlook ingest or EML rename migration steps.

## Where it lives

forge-cockpit-web/docs/outlook-owa-eml-dual-architecture.md

## How it fits the ecosystem

Teams ingest has no EML equivalent — preview/chunk text only per teams dual-architecture doc.

## Typical usage in plans and chat

EML layout versioning is Cockpit-only — do not push manifest upgrades into lcdl.

## Related terms

- [**OWA**](owa.md)
- [**cockpit**](cockpit.md)
- [**lcdl**](lcdl.md)

---

*Term page — canonical catalog entry `eml`.*
