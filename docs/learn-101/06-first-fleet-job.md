---
content_id: forge.docs.fleet.first-fleet-job
canonical_owner: forge-fleet
primary_persona: operator
reader_stage: adopt
maturity: demonstrated
evidence_level: canonical_doc
refresh_policy: on_claim_change
last_reviewed: '2026-07-03'
---

# Learn 101 — Your first Fleet job

**Audience:** Developers who completed local install and want a guided **`curl`** lab. **Outcome:** submit a **`docker_argv`** job with **`curl`**, poll lifecycle states, inspect stdout/stderr, optionally cancel.

## Prerequisites

- Fleet listening (**[Install locally](02-install-run-local-dev.md)**).
- Docker reachable by the Fleet process (**`docker info`** succeeds as that OS user).

## Mental flow

```text
POST /v1/jobs   -->   queued   -->   running   -->   completed | failed | canceled
```

```blueprint-diagram
key: state
alt: Fleet job status transitions
caption: Jobs advance from queued through running to a terminal result.
fallback_ascii: |
  queued -> running -> completed
  queued -> running -> failed
```

## Happy path

```bash
export FLEET_BASE_URL=http://127.0.0.1:18765
curl_auth=( )
[[ -n "${FLEET_TOKEN:-}" ]] && curl_auth=( -H "Authorization: Bearer ${FLEET_TOKEN}" )
[[ -n "${FLEET_BEARER_TOKEN:-}" ]] && curl_auth=( -H "Authorization: Bearer ${FLEET_BEARER_TOKEN}" )

JOB_JSON=$(curl -sS "${curl_auth[@]}" -w '\n%{http_code}' -X POST "${FLEET_BASE_URL}/v1/jobs" \
  -H 'Content-Type: application/json' \
  -d '{
    "kind": "docker_argv",
    "argv": ["docker","run","--rm","hello-world"],
    "session_id":"learn101-demo",
    "meta":{"container_class":"job"}
  }')

HTTP_CODE=$(echo "$JOB_JSON" | tail -n1)
JOB_JSON=$(echo "$JOB_JSON" | sed '$d')
[[ "$HTTP_CODE" == "201" ]] || { echo "expected HTTP 201 from POST /v1/jobs, got ${HTTP_CODE}"; echo "$JOB_JSON"; exit 1; }

echo "$JOB_JSON" | head -c 600; echo
JOB_ID=$(echo "$JOB_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))")
[[ -n "$JOB_ID" ]] || { echo "missing job id"; exit 1; }

curl -sS "${curl_auth[@]}" "${FLEET_BASE_URL}/v1/jobs/${JOB_ID}" | python3 -m json.tool | head -n 80
```

Poll until **`status`** leaves **`queued`** → **`running`** → **`completed`** (or **`failed`**):

```bash
for i in $(seq 1 30); do
  curl -sS "${curl_auth[@]}" "${FLEET_BASE_URL}/v1/jobs/${JOB_ID}" | python3 -c \
    "import sys,json; j=json.load(sys.stdin); print(j['status'], len(j.get('stdout_tail','')))"; \
  sleep 1
done
```

Full stdin/stdout tails plus **`docker_argv`** echo live on **`GET /v1/jobs/{id}`**—trim output with **`jq`** filters when noisy.

### Cancel (optional)

```bash
curl -sS "${curl_auth[@]}" -X POST "${FLEET_BASE_URL}/v1/jobs/${JOB_ID}/cancel" | python3 -m json.tool
```

## Verify

| Check | Expected |
|-------|-----------|
| **`POST /v1/jobs`** | **HTTP 201**, JSON **`id`**, **`status`: `queued`** (or **`ok`**) |
| **`GET /v1/jobs/{id}`** | **`status`** transitions to terminal state |
| **`hello-world`** demo | **`completed`** with **`stdout_tail`** referencing greeting |

## Troubleshooting

| Symptom | Likely fix |
|---------|------------|
| **`400`** **`invalid_body`** right after create | Body must include **`"kind": "docker_argv"`** and a string **`argv`** array (**[job-create-request schema](../reference/02-schemas-and-openapi.md)**) |
| Jobs stuck **`queued`** | Docker daemon/socket unreachable—see **[Troubleshooting](../operate-301/04-troubleshooting.md)** · **`docker: not found`** |
| Immediate **`failed`** | Inspect **`stderr_tail`** / **`meta.failure`** JSON via **`GET`** |
| **`401`/`403`** | Provide bearer consistent with bind address (**[Security](../operate-301/01-security.md)**) |

## Schema + protocol references

| Artifact | Location |
|----------|-----------|
| **`job-create-request`** schema | **[Schemas](../reference/02-schemas-and-openapi.md)** · **`docs/schemas/job-create-request.schema.json`** |
| Route semantics | **[HTTP API](../reference/01-http-api-reference.md)** |

## Next steps

| Topic | Doc |
|-------|-----|
| Copy-ready **`curl`** expansions | **[Examples hub](../build-201/05-examples-and-recipes.md)** · **[Integration recipes](../build-201/06-integration-recipes-index.md)** |
| Workspace uploads | **[Workspace upload](../build-201/01-workspace-upload.md)** |
| **`/admin/`** visibility | **[Admin dashboard & Studio](07-admin-dashboard-and-studio.md)** |

## Executive capsule

**Audience:** Developers who completed local install and want a guided **`curl`** lab. **Outcome:** submit a **`docker_argv`** job with **`curl`**, poll lifecycle states, inspect stdout/stderr, optionally cancel. Maturity: **demonstrated**.

## Who this is for

Operators and delivery leads at the **adopt** stage. Skim the executive capsule first; agents should respect the page frontmatter contract.

## Evidence and maturity

Maturity: **demonstrated**. Statements here reflect the owning repo (`forge-fleet`) at `last_reviewed`; treat anything not explicitly marked as demonstrated as design direction rather than a shipped guarantee.

## Trust boundary

Forge keeps humans in charge of promotion, approval, and release decisions; automation proposes and executes only within approved boundaries described here.

## The problem this solves

Teams adopting AI-assisted delivery need structure they can trust before they scale it. This page addresses that gap for its topic: it explains the situation the reader is in, the failure mode without the mechanism described here, and the outcome when it is applied.

## How it fits the Forge ecosystem

This page belongs to its owning repo's canonical documentation and links outward to the related Forge surfaces (methodology in Blueprints, product docs in each product handbook, adoption narrative on forgesdlc.com). Follow the related links to stay on the governed path.
