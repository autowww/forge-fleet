# 08 — Agentic dev rail (maintainers)

How `fleet_server/agentic_dev_job.py` and `deploy/agentic-dev/` turn one approved Roadrunner task into a pushed `agent/*` branch and a pull request, on Granite or any Fleet peer, without SSH and without copying code from a laptop.

## Pieces

| Piece | Path | Role |
|---|---|---|
| Job module | `fleet_server/agentic_dev_job.py` | Validate envelope, courier state machine, image build, container run, redaction, peer forwarding |
| Container image | `deploy/agentic-dev/Dockerfile` | Debian slim + git + python3 + node + `cursor-agent` (official installer; version label) |
| In-container pipeline | `deploy/agentic-dev/run_task.py` | clone → base_sha → branch → cursor → path guard → secret scan → verify → commit → fetch/rebase → push → PR |
| Review job | kind `code_review_task` (same image) | Re-verify pushed SHA, deterministic checks, merge via GitHub API after operator confirm (forge-workcells `code_review_worker`) |
| Tests | `fleet_server/test_agentic_dev_job.py`, `tests/test_workspace_bundle_source_guard.py` | Validation, courier, redaction, guards |

## Host configuration (`~/.config/forge-fleet/forge-fleet.env`)

| Variable | Default | Meaning |
|---|---|---|
| `FLEET_AGENTIC_GIT_TOKEN` | — (required) | Fine-grained PAT for the allowlisted repos: Contents rw, Pull requests rw, Metadata r. Rotate every 90 days |
| `FLEET_AGENTIC_REPO_ALLOWLIST` | `autowww/*` | Comma-separated glob list |
| `FLEET_AGENTIC_DEV_RUNNER` | `docker` | `docker` (container) or `host` (runs `run_task.py` directly — tests and hosts without Docker) |
| `FLEET_AGENTIC_DEV_IMAGE` | content hash of `deploy/agentic-dev` | Override to pin an image; otherwise Fleet builds `forge-agentic-dev:<hash>` on first use |
| `FLEET_AGENTIC_DEV_MAX_RUNNING` | `2` | Capacity for `container_class=agentic_dev` on this node |
| `FLEET_AGENTIC_DEV_MEMORY` / `FLEET_AGENTIC_DEV_CPUS` | `4g` / `2` | Container limits |
| `FLEET_AGENTIC_DEV_NODE` | unset | Set `1` to advertise this node as an agentic-dev node to peers |
| `FLEET_BUNDLE_SOURCE_FILE_LIMIT` / `FLEET_BUNDLE_ALLOW_SOURCE` | `20` / unset | Source-bundle guard for job workspaces |

The Cursor key is **not** configured on the host. It is attached per task from localhost (submit body or `POST …/{id}/credential`).

## Container run

```
docker run --rm --name fleet-agentic-<id> --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 1024 --memory 4g --cpus 2 --env-file <job>/task/.env.runtime \
  -e TASK_FILE=/task/task.json -e OUT_DIR=/out \
  -v <data>/agentic-dev/<id>/task:/task:ro -v <data>/agentic-dev/<id>/out:/out  forge-agentic-dev:<hash>
```

`.env.runtime` (0600) holds `CURSOR_API_KEY` and `GIT_TOKEN` for the lifetime of the run and is deleted afterwards. The token reaches git through `GIT_ASKPASS`, never through the remote URL.

## Result (`<data>/agentic-dev/<id>/out/result.json`, also `GET …/{id}` → `result`)

`task_id, repo, branch, base_ref, base_sha, head_sha, pr_url, pr_number, changed_files, verify[] {cmd, exit_code}, test_instructions[], status ∈ {pushed, held, failed}, hold_reason, steps[]`. Job status maps `pushed → completed`, `held → held`, else `failed`.

## Stale and hold matrix (R09)

| Condition | `status` / `hold_reason` | Branch pushed? | Operator action |
|---|---|---|---|
| Envelope repo/branch invalid | `held` / `invalid_envelope` | no | Fix the task text; new approval |
| Credentials missing in container | `held` / `credentials_missing` | no | Check courier and `git-identity` |
| Clone failed (auth, repo, base_ref) | `failed` / `clone_failed` | no | Check token scopes and `base_ref` |
| Cursor exited non-zero or timed out | `failed` / `cursor_failed` | no | Read `cursor-output.txt`; retry with a new approval |
| No files changed | `held` / `no_changes` | no | Goal was a no-op or unclear |
| Change outside `allow_paths` or inside `deny_paths` | `held` / `path_violation` (`offending_paths`) | no | Widen allow list **in a new approved task**, or reject |
| Secret-looking content in changed files | `held` / `secret_pattern` | no | Never approve; inspect |
| A verify command failed | `held` / `verify_failed` | no | Inspect `steps.log`; new task |
| Upstream moved and rebase conflicts | `held` / `stale_conflict` (`conflicts[]`) | no | Human resolves or re-runs the task on the new base |
| Push rejected (ruleset, token) | `failed` / `push_failed` | no | Check `agent/**` ruleset and token |
| PR creation failed after push | `completed` with `pr_error` | yes | Open the PR manually or re-run review submit |

The pipeline never force-pushes, never pushes to `base_ref`, and never resolves conflicts.

## Branch GC (R09)

`fleet_server/branch_gc_job.py` lists `agent/*` branches for each allowlisted repo via the GitHub API and deletes those with no open PR whose last commit is older than `FLEET_AGENTIC_BRANCH_TTL_DAYS` (default 14). Trigger: `POST /v1/admin/agentic-dev/branch-gc` with `{"dry_run": true|false, "repos": [...]}`; a daily run is wired through the space-guardian scheduler when `FLEET_AGENTIC_BRANCH_GC=1`.

## Peer spread (R10)

`node: auto` picks local when `free > 0`, else the first registered peer whose `GET /v1/admin/agentic-dev/capacity` reports `agentic_dev: true` and `free > 0`. `node: <peer_id>` forwards directly (409 `peer_unavailable` when unknown). Forwarding posts the same envelope with `node: local` through the remote-peer proxy; the credential is attached on that hop only. Each node needs its own token and builds its own image from the same `deploy/agentic-dev` at the same Fleet version.

## Smoke on a host

```bash
curl -fsS -H "Authorization: Bearer $FORGE_FLEET_BEARER_TOKEN" "$FORGE_FLEET_BASE_URL/v1/admin/cursor-cli/status"
curl -fsS -H "Authorization: Bearer $FORGE_FLEET_BEARER_TOKEN" "$FORGE_FLEET_BASE_URL/v1/admin/git-identity"
```

Both must be `ok: true` before Roadrunner submits a task.
