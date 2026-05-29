# OpenAPI fragments

Edit `paths/*.json`, `components.json`, and `openapi-root.json` (not the bundled file).

| File | Contents |
|------|----------|
| `openapi-root.json` | `openapi`, `info`, `servers` |
| `components.json` | `securitySchemes`, `schemas` (`$ref` to sibling `../*.schema.json`) |
| `paths/*.json` | HTTP paths grouped by API area — see [`paths/README.md`](paths/README.md) |

Regenerate the deploy/CI bundle:

```bash
python3 scripts/bundle_openapi.py
```

Writes `../openapi.json` (generated, gitignored; prefer editing fragments here). Parent index: [`../README.md`](../README.md).
