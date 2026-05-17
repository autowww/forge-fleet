# Forge Fleet — usage examples & recipes companion

For the **topic-based** examples hub (Python / TypeScript / jobs / CI smoke stubs), start at **[Examples library](../examples/README.md)** — this page is the long-form **`curl`** + **`jq`** appendix.

See **[Integration recipes hub](06-integration-recipes-index.md)** for scenario → doc wiring before scanning every snippet below.

Command-line patterns for **`curl`** against a running **`fleet_server`**. Replace host and port with your install (**`127.0.0.1:18765`**, **`18766`**, or a TLS front-end). See **[HTTP API reference](../reference/01-http-api-reference.md)** for every route and **[What is Fleet?](../learn-101/01-what-is-fleet.md)** for ports and mental model.

Set a shell prefix when experimenting:

```bash
export FLEET_BASE_URL='http://127.0.0.1:18765'   # no trailing slash; no /v1 suffix
export FLEET_TOKEN='your-bearer-here'               # optional on loopback; omit export when empty
```

When **`FLEET_BEARER_TOKEN`** is set and Fleet listens on a **non-loopback** address, every **`/v1/*`** call must pass **`Authorization`**. For copy-paste, build a **`curl`** auth flag array (empty when no token):

```bash
curl_auth=( )
[[ -n "${FLEET_TOKEN:-}" ]] && curl_auth=( -H "Authorization: Bearer ${FLEET_TOKEN}" )
```

## Read-only checks

**Version**

```bash
curl -sS "${FLEET_BASE_URL}/v1/version" | jq .
```

**Health** (live host CPU/RAM/load snapshot; also used from inside jobs when host-metrics injection is enabled)

```bash
curl -sS "${curl_auth[@]}" "${FLEET_BASE_URL}/v1/health" | jq .
```

**Template catalog** (e.g. `host_cpu_probe` for Studio **Test Fleet**)

```bash
curl -sS "${curl_auth[@]}" "${FLEET_BASE_URL}/v1/templates" | jq .
```

**Container type catalog** (on-disk **`types.json`** + materialized capabilities)

```bash
curl -sS "${curl_auth[@]}" "${FLEET_BASE_URL}/v1/container-types" | jq .
```

**Admin snapshot** (large JSON: jobs summary, integrations, thermal hints). Limit payload for a quick peek:

```bash
curl -sS "${curl_auth[@]}" "${FLEET_BASE_URL}/v1/admin/snapshot" | jq '{ ok: .ok, meta: .meta | {version, energy_ledger_kwh}, jobs_by_status, sqlite: .meta.sqlite_path }'
```

(If `jq` is unavailable, drop the filter and scroll in a pager.)

**Telemetry** (historical samples; **`period`** is required)

```bash
curl -sS "${curl_auth[@]}" "${FLEET_BASE_URL}/v1/telemetry?period=last_1_hour&limit=5" | jq .
```

**Cooldown summary** (aggregated LLM throttle waits recorded by clients)

```bash
curl -sS "${curl_auth[@]}" "${FLEET_BASE_URL}/v1/cooldown-summary?period=today" | jq .
```

## Submit a trivial `docker_argv` job (requires Docker on the Fleet host)

**`argv`** is the full container CLI invocation as a JSON string array (usually **`docker`**, **`run`**, image, command). **`meta.container_class`** is required, must match **`^[a-z][a-z0-9_-]{0,127}$`**, and cannot be **`empty`**. It is stored for **telemetry / admin** grouping; align it with a **`container_class`** from **`GET /v1/container-types`** when you want types and jobs to line up in **`/admin/`** (the **`job`** category in the default catalog is **`host_cpu_probe`**, which is intended for the probe image—use a **`docker run … echo`** pattern only with a **custom** job type you add to **`types.json`**, or use a throwaway label like below for experiments).

```bash
JOB_BODY=$(jq -nc \
  --arg sid "curl-example-$(date +%s)" \
  '{
    kind: "docker_argv",
    argv: ["docker", "run", "--rm", "alpine:3.20", "echo", "fleet-ok"],
    session_id: $sid,
    meta: { container_class: "doc_example_echo", workload_label: "handbook-curl" }
  }')

curl -sS "${curl_auth[@]}" -X POST "${FLEET_BASE_URL}/v1/jobs" \
  -H 'Content-Type: application/json' \
  -d "$JOB_BODY" | tee /tmp/fleet-job-create.json | jq .

JOB_ID=$(jq -r '.id' /tmp/fleet-job-create.json)
curl -sS "${curl_auth[@]}" "${FLEET_BASE_URL}/v1/jobs/${JOB_ID}" | jq '{ status, exit_code, stdout: .stdout[0:200] }'
```

Pick a **`job`** row from **`GET /v1/container-types`** when you want **`meta.container_class`** to match operator-visible **container types**:

```bash
curl -sS "${curl_auth[@]}" "${FLEET_BASE_URL}/v1/container-types" \
  | jq -r '.types_materialized[] | select(.category_id=="job") | "\(.id)\t\(.container_class)"'
```

## Studio-style CPU probes (`/v1/admin/test-fleet`)

The Lenses workspace server calls this with the operator’s saved bearer. Minimal **`curl`**:

```bash
curl -sS "${curl_auth[@]}" -X POST "${FLEET_BASE_URL}/v1/admin/test-fleet" \
  -H 'Content-Type: application/json' \
  -d '{"count": 5}' | jq .
```

## Record a cooldown wait (`POST /v1/cooldown-events`)

Example body (thermal guard):

```bash
curl -sS "${curl_auth[@]}" -X POST "${FLEET_BASE_URL}/v1/cooldown-events" \
  -H 'Content-Type: application/json' \
  -d '{"duration_s": 2.5, "kind": "thermal_llm_guard", "meta": {"note": "doc example"}}' | jq .
```

## Git self-update from automation (`POST /v1/admin/git-self-update`)

Same auth as other **`/v1/*`** routes. Typical **`curl`** (no secrets in shell history: prefer env vars):

```bash
curl -sS -X POST "${FLEET_BASE_URL}/v1/admin/git-self-update" \
  -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json' \
  -d '{}' | jq .
```

On **system** installs under **`/opt/forge-fleet`**, expect **`400`** with **`system_root_install_command`** instead of an in-process upgrade; see [API-REFERENCE.md](../reference/01-http-api-reference.md). The dev script **`./scripts/update-fleet.sh --remote-git-self-update`** wraps this after **`git push`**; see the [README](../../README.md).

## Forge Lenses environment (reference)

Lenses Studio typically sets:

| Variable | Role |
|----------|------|
| **`LENSES_FLEET_URL`** | Base URL of Fleet (**`http://host:port`**, no **`/v1`**) |
| **`LENSES_FLEET_TOKEN`** | Bearer sent by the **workspace server** on **`/v1/*`** calls |

Operators still open **`/admin/`** in a browser at the same host/port (unless a reverse proxy maps paths).

## List managed Forge LLM services

```bash
curl -sS "${curl_auth[@]}" "${FLEET_BASE_URL}/v1/container-services" | jq .
```

Start/stop use **`POST /v1/container-services/{id}/start`** and **`…/stop`** (or the legacy **`/v1/services/forge-llm/*`** aliases). Records live under **`$FLEET_DATA_DIR/etc/services/`**; see [API-REFERENCE.md](../reference/01-http-api-reference.md) and the [README](../../README.md) section on container types.

## Handbook build (Markdown → static HTML)

The **forge-fleet-website** repo vendors this tree as a **`forge-fleet/`** submodule and runs **`python3 generator/build-site.py`**: all **`*.md`** here (except **`blueprints/`**, **`kitchensink/`**, **`.github/`**) become flat **`website/*.html`** pages, with same-repo Markdown links whose targets end in **`.md`** rewritten to **`.html`**. PNG assets under **`docs/assets/`** are copied into **`website/assets/`** during that build.
