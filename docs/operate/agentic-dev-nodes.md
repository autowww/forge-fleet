# Agentic dev nodes across the Fleet mesh

Any Fleet host can run Roadrunner repo tasks (`container_class=agentic_dev`) once it has Docker, a GitHub token, and the `deploy/agentic-dev` image. Code never moves between nodes: every node clones from GitHub.

## Enable a node

1. Put `FLEET_AGENTIC_GIT_TOKEN=<fine-grained PAT>` and `FLEET_AGENTIC_DEV_NODE=1` in `~/.config/forge-fleet/forge-fleet.env`, then `systemctl --user restart forge-fleet.service` (or the system unit).
2. Optional: `FLEET_AGENTIC_DEV_MAX_RUNNING=<n>` (default 2), `FLEET_AGENTIC_DEV_MEMORY`, `FLEET_AGENTIC_DEV_CPUS`.
3. Verify from any admin client:

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE/v1/admin/cursor-cli/status"
curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE/v1/admin/git-identity"
curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE/v1/admin/agentic-dev/capacity"
```

The first task on a node builds `forge-agentic-dev:<hash>` locally (a few minutes); later tasks reuse it until `deploy/agentic-dev` changes with a Fleet release.

## Placement

| `node` in the task | Behaviour |
|---|---|
| `local` (default) | Run on the node that received the request |
| `auto` | Local when it has a free slot, else the first registered peer whose capacity endpoint reports `agentic_dev: true` and `free > 0` |
| `<peer-id>` | Forward to that registered peer; `409 peer_unavailable` when unknown |

`POST /v1/mesh/offload/advise` with `{"workload": "agentic_dev"}` returns the ranked candidates without submitting anything.

## Credentials per node

- Git token: one per node, scoped to the same repo allowlist. Never forwarded between peers.
- Cursor key: supplied by the submitting side per task; when a task is forwarded, the key travels on that single hop inside the proxied request body and is held only in the receiving node's runtime env file for the duration of the container.

## Related

- [maintainers/08-agentic-dev-rail](../maintainers/08-agentic-dev-rail.md)
- [design/granite-operator-boundary](../design/granite-operator-boundary.md)
- [reference/01-http-api-reference](../reference/01-http-api-reference.md) § Agentic dev rail
