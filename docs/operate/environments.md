# Fleet environment provisioning

Generic DEV/PROD (and other) compose environments are managed through the Fleet **environments API** and optionally through **Lenses Studio → Publish → Environments**.

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/environments` | List environments (auto-adopts existing Market Studio stacks) |
| GET | `/v1/environments/templates` | List templates |
| POST | `/v1/environments` | Provision (`seed`: `clean` or `replicate`) |
| GET | `/v1/environments/provision-log` | Async progress log |

See [ADR: Fleet environments](../adr/adr-fleet-environments.md) and `docs/schemas/environment.schema.json`.

## Market Studio operator

Workstation Market Studio persists the target gateway in `data/operator/data-plane-pref.json`:

```json
{
  "mode": "remote",
  "gateway_url": "https://granite.forgedc.net/v1/app-gateways/market-studio-dev",
  "environment_label": "market-studio-dev"
}
```

Settings → **Granite environment** lists gateways from Fleet when credentials are configured. Launcher scripts seed the pref only when absent.

## Lenses Studio

Enable server flag `LENSES_EXPERIMENTAL_ENVIRONMENTS=1` and client `VITE_EXPERIMENTAL_ENVIRONMENTS=1`, then open **Publish → Environments**.
