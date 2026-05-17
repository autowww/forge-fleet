# Examples — Python (stdlib)

Uses **`urllib`** only (Python 3.11+). Set **`BASE`** / **`FLEET_TOKEN`** env vars like **[curl.md](curl.md)**.

```python
#!/usr/bin/env python3
import json
import os
import urllib.request

BASE = os.environ.get("BASE", "http://127.0.0.1:18765").rstrip("/")
TOKEN = os.environ.get("FLEET_TOKEN", "")


def api(method: str, path: str, body: dict | None = None):
    url = f"{BASE}{path}"
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if body else {}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def main():
    ver = api("GET", "/v1/version")
    print("version:", json.dumps(ver)[:240])

    job = api(
        "POST",
        "/v1/jobs",
        {
            "kind": "docker_argv",
            "argv": ["docker", "run", "--rm", "hello-world"],
            "session_id": "python-example",
            "meta": {"container_class": "job"},
        },
    )
    job_id = job["id"]
    print("created:", job_id, job.get("status"))

    snap = api("GET", f"/v1/jobs/{job_id}")
    print("poll:", snap.get("status"))


if __name__ == "__main__":
    main()
```

Schema references: **`job-create-request`** in **`docs/schemas/`** via **[Schemas](../reference/02-schemas-and-openapi.md)**.

## Purpose

Minimal **stdlib** **`urllib`** client for version, job create, and job poll.

## Prerequisites

Python 3.11+, **`BASE`** / **`FLEET_TOKEN`** as in **[curl.md](curl.md)**.

## Copy-paste steps

Save the script, adjust **`argv`** / **`session_id`**, run **`python3`** against a dev Fleet.

## Expected output

Prints truncated version JSON, new job **`id`**, and polled **`status`**.

## Error handling

**`urllib`** raises on non-2xx; wrap per **[error-handling.md](error-handling.md)** patterns.

## Security notes

Keep tokens in environment variables, not source control.

## Related

- **[jobs.md](jobs.md)**
- **[HTTP API](../reference/01-http-api-reference.md)**

## Validation status

- Inline job body matches **`job-create-request`** shape; **[`payloads/valid/job-create-request.json`](payloads/valid/job-create-request.json)** is CI-validated.
- OpenAPI: **[`../schemas/openapi.json`](../schemas/openapi.json)**.
