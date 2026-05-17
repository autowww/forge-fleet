# Examples — CI smoke hook

Pseudo-job GitHub Actions fragment:

```yaml
- name: Fleet smoke
  run: |
    set -euo pipefail
    BASE=http://127.0.0.1:18765
    curl -fsS "$BASE/v1/version" >/tmp/version.json
    docker info >/dev/null 2>&1 || { echo "skip heavy job"; exit 0; }
    curl -fsS -X POST "$BASE/v1/jobs" \
      -H 'Content-Type: application/json' \
      -d '{"kind":"docker_argv","argv":["docker","run","--rm","hello-world"],"session_id":"ci","meta":{"container_class":"job"}}'
```

Adapt **`BASE`** / bearer headers per environment.

## Purpose

Minimal GitHub Actions fragment: **version** GET + optional **`docker_argv`** smoke job.

## Prerequisites

Fleet listening at **`BASE`**; Docker optional (early exit if missing).

## Copy-paste steps

Paste into a workflow job; add **`Authorization`** when your dev server enforces bearer auth.

## Expected output

**`/v1/version`** JSON written to **`/tmp/version.json`**; job create returns **201** when Docker works.

## Error handling

**`curl -fsS`** fails on HTTP errors; guard Docker availability before POST as shown.

## Security notes

Use **`GITHUB_SECRETS`** for tokens—never inline production bearers in YAML.

## Related

- **[jobs.md](jobs.md)** · **[curl.md](curl.md)**
- **[HTTP API](../reference/01-http-api-reference.md)**

## Validation status

- Inline JSON matches **`job-create-request`** (see **[`payloads/valid/job-create-request.json`](payloads/valid/job-create-request.json)**).
- CI **`check-docs-examples.py`** enforces **`docker_argv`** + **201** language in maintained snippets.
