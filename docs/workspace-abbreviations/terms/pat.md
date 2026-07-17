---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "PAT — Personal Access Token"
description: "GitHub PAT for Lenses .lenses-repo/<login>/ overlays and private git+ssh clone auth contexts.
"
term_abbr: "PAT"
term_category: "platform"
---

# PAT — Personal Access Token

GitHub PAT for Lenses .lenses-repo/<login>/ overlays and private git+ssh clone auth contexts.


## What it is

Stored in Lenses local session after GitHub auth — enables shared repo overlay writes.

## When people say this

When configuring Lenses GitHub integration or private submodule fetch — not Fleet bearer token.

## Where it lives

forge-lenses/ docs/handbook-public/17-security-and-local-first.md

## How it fits the ecosystem

Fleet uses FORGE_FLEET_BEARER_TOKEN — different token family from GitHub PAT.

## Typical usage in plans and chat

Never paste PATs into plans or commits — reference secret storage location only.

## Do not confuse with

FTS

## Related terms

- [**fl**](fl.md)

---

*Term page — canonical catalog entry `pat`.*
