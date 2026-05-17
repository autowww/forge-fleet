# Learn 101 — Your first Fleet job

**Audience:** Developers who completed local install and want a guided **`curl`** lab. **Outcome:** submit a **`docker_argv`** job with **`curl`**, poll lifecycle states, inspect stdout/stderr, optionally cancel.

## Prerequisites

- Fleet listening (**[Install locally](02-install-run-local-dev.md)**).
- Docker reachable by the Fleet process (**`docker info`** succeeds as that OS user).

## Mental flow

```text
POST /v1/jobs   -->   queued   -->   running   -->   completed | failed | canceled
```

```blueprint-diagram-ascii
key: state
alt: Fleet job status transitions
caption: Jobs advance from queued through running to a terminal result.
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
