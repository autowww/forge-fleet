# Granite git identity for the agentic dev rail

Roadrunner tasks running on Granite push `agent/*` branches and open pull requests as a dedicated GitHub identity. This page is the operator checklist; nothing here involves SSH to Granite.

## Token

| Item | Value |
|---|---|
| Kind | GitHub **fine-grained** personal access token (or a GitHub App installation token if you later move to an App) |
| Resource owner | `autowww` |
| Repository access | Only the repositories Roadrunner may touch (same list as `FLEET_AGENTIC_REPO_ALLOWLIST`) |
| Permissions | Contents: read and write · Pull requests: read and write · Metadata: read |
| Expiry | 90 days; renew before expiry (see `GET /v1/admin/git-identity` → `expires_hint`) |
| Storage | `~/.config/forge-fleet/forge-fleet.env` on Granite as `FLEET_AGENTIC_GIT_TOKEN=…` (mode 0600). Not in git, not in Matrix, not in job bodies |

Rulesets on each repo keep this identity honest: `main`/`master` require a PR plus the `test` check, and the agent lane accepts only `agent/(roadrunner|reviewer)/req_task_<8 hex>-<slug>` branches without force pushes (`docs/rulesets/*.json` in forge-agents and forge-workcells).

## Install on Granite without SSH

The env file is operator-owned configuration. Two paths that stay within the Fleet boundary:

1. **Fleet env update job** — submit a Fleet admin job on Granite that appends the line to the env file and restarts the unit (`POST /v1/jobs` with `argv: ["bash","-lc", …]` is allowed for the service user; the token goes in the job's `env` field, never in `argv`). After the restart, `GET /v1/admin/git-identity` must return `ok: true`.
2. **One-time console step** by the operator at the host (physical/VM console), when a job is not appropriate. Record the date on the program page.

## Verify

```bash
curl -fsS -H "Authorization: Bearer $FORGE_FLEET_BEARER_TOKEN" "$FORGE_FLEET_BASE_URL/v1/admin/git-identity"
# {"ok": true, "login": "…", "token_kind": "fine_grained_pat", ...}
```

`400 git_token_not_configured` means the variable is missing; `400 github_unreachable` or `401` means the token is wrong or expired.

## Rotation

1. Mint the new token with identical scopes.
2. Replace the value in the env file and restart Fleet.
3. Confirm `git-identity`, then revoke the old token in GitHub.
4. Branch GC continues to work because it uses the same variable.

## Cursor key (reminder)

The Cursor API key is **never** stored on Granite. It is attached per task from localhost by the Roadrunner courier (`forge-roadrunner-courier.service`) or in the submit body, and lives only in the container's runtime env file for one run.
