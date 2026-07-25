---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "XL — Triage size XL"
description: "Extra-large — >400k token order; multi-repo program, long-running loops, broad refactors.
"
term_abbr: "XL"
term_category: "cursor_plan"
---

# XL — Triage size XL

Extra-large — >400k token order; multi-repo program, long-running loops, broad refactors.


## What it is

Highest tier — explicit human checkpoints, branch strategy, avoid unbounded agent fan-out.

## When people say this

Workspace-wide KS remediation, v4 lmeta cutover across cockpit+lcdl+cdp, major methodology rewrites.

## Where it lives

.cursor/rules/forge-triage.mdc

## How it fits the ecosystem

May still refuse autonomous push/deploy without explicit user ask per git workflow rules.

## Typical usage in plans and chat

XL plans split into PRs (split-to-prs skill), dry-run merges, per-repo commits — never one giant commit.

## Related terms

- [**L**](l.md)
- [**subagent**](subagent.md)

---

*Term page — canonical catalog entry `xl`.*
