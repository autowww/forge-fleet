# Forge gateway — Cursor CLI lane

Cursor CLI models route to the **CLI lane** (not Ollama). Catalog: [`configs/cursor_cli_models.yaml`](../configs/cursor_cli_models.yaml). Discovery: `GET /v1/llm/cursor/models` and enabled rows on `GET /v1/models`.

## Gateway endpoints (redirect all Cursor work here)

| Endpoint | Use |
|----------|-----|
| `POST /v1/chat/completions` | OpenAI-compatible chat; `model` = catalog `gateway_id` |
| `GET /v1/models` | Ollama pins **plus** enabled Cursor CLI models (`owned_by: forge-gateway-cursor-cli`) |
| `GET /v1/llm/cursor/models` | Full mapping table, labels, aliases, endpoint index |
| `GET /v1/llm/jobs/{job_id}` | Poll async CLI jobs (`X-Forge-Async: 1`) |
| `GET /v1/llm/telemetry/summary` | Token/request rollups (`meta.lane = cli`) |
| `POST /v1/llm/telemetry/events` | Optional `agent_run` overlay from consumers |

**Upstream (laptop / worker):** `cli_bridge.py` `POST /v1/chat/completions` when `FORGE_LLM_CLI_UPSTREAM_URL` is set.

## Model id mapping (gateway → cursor-agent)

Open WebUI uses `prefix_id: forge-llm` on the gateway connection, so the UI may show **`forge-llm.composer-2.5`**. Send either the bare `gateway_id` or the prefixed id; the gateway normalizes `forge-llm.` away.

| UI label (docs) | `gateway_id` (request) | `cursor_id` (argv `--model`) |
|-----------------|------------------------|------------------------------|
| F Composer 2.5 | `composer-2.5` | `composer-2.5` |
| F Composer → 2.5 | `composer` | `composer-2.5` |
| F Grok 4.7 High | `grok-4.7-high` | `grok-4.7-high` |
| F GPT 5.3 Codex | `gpt-5.3-codex` | `gpt-5.3-codex` |
| F Claude 4.6 Sonnet (thinking) | `claude-4.6-sonnet-medium-thinking` | same |
| F Claude 4.6 Opus (thinking) | `claude-4.6-opus-high-thinking` | same |
| F Gemini 3 Flash | `gemini-3-flash` | `gemini-3-flash` |

Extend the YAML for more ids from `cursor-agent models` on your host. Set `enabled: false` to hide from `GET /v1/models` without removing routing. Override path: `FORGE_LLM_CLI_MODELS_FILE`.

Legacy prefix rule still applies: `composer*`, `grok*` match the CLI lane even if not listed in the YAML.

## Environment

| Variable | Role |
|----------|------|
| `CURSOR_AGENT_BIN` | `cursor-agent` binary on the gateway or worker host |
| `FORGE_LLM_CLI_CWD` | Default workspace when `forge_cursor.workspace` omitted (default `/tmp/forge-llm-cli`) |
| `FORGE_LLM_CLI_WORKSPACE_ROOTS` | Comma-separated allowed workspace roots |
| `FORGE_LLM_CLI_UPSTREAM_URL` | Laptop or sidecar bridge base URL |
| `FORGE_LLM_CLI_UPSTREAM_TOKEN` | Bearer for upstream bridge |
| `FORGE_LLM_CLI_UPSTREAM_FILE` | JSON override (`url`, `token`, or `"mode":"queue"`) |
| `FORGE_LLM_CLI_QUEUE_DIR` / `FORGE_LLM_CLI_RESULT_DIR` | Disk queue for Granite (worker: `scripts/cli_queue_worker.py`) |
| `FORGE_LLM_CLI_ASYNC_TIMEOUT_S` | Sync allowed only below this threshold unless `X-Forge-Async: 1` (default `180`) |

## Request extension

```json
{
  "model": "composer-2.5",
  "messages": [{"role": "user", "content": "..."}],
  "forge_cursor": {
    "mode": "ask",
    "workspace": "/path/to/repo",
    "force": false,
    "output_format": "text",
    "timeout_s": 120
  }
}
```

`mode=agent` or `timeout_s` above the async threshold requires `X-Forge-Async: 1` plus webhook headers; returns `202` with `job_id`.

## Consumers

| Flag | Location |
|------|----------|
| `FORGE_AGENT_VIA_GATEWAY=1` | `deploy/agentic-dev/run_task.py` |
| `FORGE_CURSOR_VIA_GATEWAY=1` | `forge_cursor_bridge` `CliRunner` |
| `FORGE_LLM_BASE_URL` + bearer | Gateway OpenAI base (`/v1/chat/completions`) |