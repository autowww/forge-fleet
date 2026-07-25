---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "FTS — Full-Text Search"
description: "SQLite FTS indices for local search — Lenses .lenses-local/, Cockpit message headers, KA deck index.
"
term_abbr: "FTS"
term_category: "platform"
---

# FTS — Full-Text Search

SQLite FTS indices for local search — Lenses .lenses-local/, Cockpit message headers, KA deck index.


## What it is

fl: FTS DB in lenses-local. cockpit: participant_search_text triggers. fka: DeckIndexRetriever FTS.

## When people say this

When planning local search features, contact lookup, or deck evidence retrieval — not Firebase Hosting.

## Where it lives

forge-lenses/; forge-cockpit-web/; forge-knowledge-assistant/

## How it fits the ecosystem

FTS is local-first; distinct from public site search on forgesdlc.com.

## Typical usage in plans and chat

Schema migrations for FTS tables need Cockpit layout versioning notes when touching message store.

## Do not confuse with

PAT

## Related terms

- [**fl**](fl.md)
- [**cockpit**](cockpit.md)
- [**fka**](fka.md)

---

*Term page — canonical catalog entry `fts`.*
