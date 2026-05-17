# Examples — TypeScript (`fetch`)

Targets **Node 20+** (`fetch` global). **Do not** paste bearer tokens into browsers’ devtools on shared machines—prefer env injection.

```typescript
const BASE = process.env.BASE ?? "http://127.0.0.1:18765";
const TOKEN = process.env.FLEET_TOKEN ?? "";

async function fleetFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (TOKEN) headers.set("Authorization", `Bearer ${TOKEN}`);
  const res = await fetch(`${BASE.replace(/\/$/, "")}${path}`, { ...init, headers });
  const text = await res.text();
  if (!res.ok) throw new Error(`${res.status} ${text}`);
  return JSON.parse(text);
}

async function main() {
  console.log(await fleetFetch("/v1/version"));
  const job = await fleetFetch("/v1/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      kind: "docker_argv",
      argv: ["docker", "run", "--rm", "hello-world"],
      session_id: "ts-example",
      meta: { container_class: "job" },
    }),
  });
  console.log("created", job.id, job.status);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

Run:

```bash
BASE=http://127.0.0.1:18765 FLEET_TOKEN=dev-token npx ts-node fleet-fetch-demo.ts
```

(Compile with **`tsc`** if you prefer plain **`node dist/…`**.)

## Purpose

Node **20+** example using global **`fetch`** with JSON helpers.

## Prerequisites

Node 20+ and **`BASE`** / **`FLEET_TOKEN`** env vars.

## Copy-paste steps

Run the embedded **`main`** via **`ts-node`** or compile to JS as noted above.

## Expected output

Logs **`/v1/version`** and a created job **`id`** / **`status`**.

## Error handling

Non-OK responses throw with status and body text—extend with retry/backoff as needed.

## Security notes

Avoid pasting tokens into browser devtools on shared machines.

## Related

- **[python.md](python.md)** · **[curl.md](curl.md)**
- **[HTTP API](../reference/01-http-api-reference.md)**

## Validation status

- Request bodies align with **`job-create-request.schema.json`**; fixtures under **[`payloads/valid/`](payloads/valid/)** are checked in CI.
- OpenAPI: **[`../schemas/openapi.json`](../schemas/openapi.json)**.
