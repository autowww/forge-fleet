---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "Code-hub — Code workspace hub"
description: "Primary Forge multi-repo workspace at ~/Code/ — each subfolder is its own git history.
"
term_abbr: "Code-hub"
term_category: "hub"
---

# Code-hub — Code workspace hub

Primary Forge multi-repo workspace at ~/Code/ — each subfolder is its own git history.


## What it is

Workspace root containing forgesdlc-kitchensink/, blueprints/, forge-lenses/, deploy-websites.sh,
sync-kitchensink-and-rebuild.sh, scripts/integrate-unmerged-branches.sh.

## When people say this

When running workspace-root scripts, UX auditor workbench defaults, or workspace-map orientation.

## Where it lives

/home/lzvyahin/Code/

## How it fits the ecosystem

lcdl library lives here; LCDL hub is separate under home. workbench/ux-auditor for ephemeral audits.

## Typical usage in plans and chat

One commit per project boundary — never stage across repo folders in a single commit.

## Related terms

- [**ks**](ks.md)
- [**bp**](bp.md)
- [**forge**](forge.md)

---

*Term page — canonical catalog entry `code-hub`.*
