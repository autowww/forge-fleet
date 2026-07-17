---
public_publish: true
audience: public
handbook_area: blueprints
learning_level: reference
nav_title: "MCP — Model Context Protocol"
description: "MCP servers expose tools/resources to agents — Cursor MCP file system, fccmem MCP feed adapter.
"
term_abbr: "MCP"
term_category: "platform"
---

# MCP — Model Context Protocol

MCP servers expose tools/resources to agents — Cursor MCP file system, fccmem MCP feed adapter.


## What it is

Protocol for agent tool discovery. Cockpit memory package documents API and MCP ingest paths.

## When people say this

When wiring agent tools in Cursor, SDK agents, or Fleet memory adapters — not Microsoft Copilot alone.

## Where it lives

Cursor mcps/; forge-cockpit-memory/

## How it fits the ecosystem

Distinct from M365 product APIs — MCP is agent integration layer.

## Typical usage in plans and chat

MCP plans must read tool schema descriptors before CallMcpTool per agent instructions.

## Related terms

- [**fccmem**](fccmem.md)
- [**cockpit**](cockpit.md)

---

*Term page — canonical catalog entry `mcp`.*
