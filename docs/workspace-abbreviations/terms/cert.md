---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "cert — forge-certificators"
description: "Bank health / certificator REST UI — typical dev port 11350, integrates with Fleet for git-self-update.
"
term_abbr: "cert"
term_category: "repo"
---

# cert — forge-certificators

Bank health / certificator REST UI — typical dev port 11350, integrates with Fleet for git-self-update.


## What it is

forge-certificators/ with forge-certificator CLI, example-banks/, Settings → Fleet credentials.

## When people say this

When user asks update certificator — remote Fleet POST /v1/admin/git-self-update then local refresh.

## Where it lives

forge-certificators/

## How it fits the ecosystem

Uses ff bearer token from forge-certificator-secrets.env. Separate from cockpit and cdp.

## Typical usage in plans and chat

Certificator refresh order: remote Fleet API → ~/forge-fleet update → cert reinstall on 11350.

## Related terms

- [**ff**](ff.md)

---

*Term page — canonical catalog entry `cert`.*
