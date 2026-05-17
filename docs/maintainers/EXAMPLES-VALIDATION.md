# Maintainer notes — Examples validation

| Surface | Automated today | Manual expectation |
|---------|----------------|-------------------|
| **Job create (`POST /v1/jobs`)** in fenced Markdown blocks | ✅ `python3 scripts/check-docs-examples.py` | Verifies **`kind: docker_argv`** + **`argv`** for bash (**`-d` / `--data`**), Python **`api("POST", "/v1/jobs", …)`**, and TypeScript **`fleetFetch`** |
| **`curl`** snippets (non-job routes) | ❌ | Run against a throwaway **`FLEET_DATA_DIR`** when editing payloads |
| **Python (`urllib`)** full scripts | Partial (job body only when using **`api(…)`** helper pattern) | Copy into scratch file + run locally |
| **TypeScript (`fetch`)** | Partial (job **`JSON.stringify`** body) | **`ts-node`** smoke when request shapes change |
| **OpenAPI parity** | ✅ `python3 scripts/check-docs-contracts.py` | CI workflow **`docs-contracts.yml`** |
| **Payload fixtures (`docs/examples/payloads/`)** | ✅ `python3 scripts/check-schema-examples.py` (requires **`jsonschema`**) | **`valid/*.json`** must validate; **`invalid/*.invalid.*.json`** must fail |

How **`check-docs-examples.py`** finds job creates:

1. **Markdown fences** — skips a block when the closest previous non-blank line is `<!-- docs:skip-job-schema-check -->`.
2. **Bash** — **`curl`** with **`-X POST`**, payload flag (**`-d` / `--data` / `--data-binary`**), URL ending in **`/v1/jobs`** (not **`/cancel`**).
3. **Python** — **`api("POST", "/v1/jobs", { … })`** parsed with **`ast.literal_eval`** so f-strings elsewhere do not confuse brace matching.
4. **TypeScript** — **`fleetFetch("/v1/jobs", …)`** plus **`method: "POST"`**; body must visibly include **`docker_argv`** or parse as JSON (object keys quoted).

Future hooks:

1. Extend link coverage beyond **`.md`** targets (**`check-docs-links.py`**).
2. Optional Playwright replay of **Learn 101** **`curl`** bundles against a disposable port.
