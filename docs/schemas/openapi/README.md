# OpenAPI fragments

Edit `paths/*.json`, `components.json`, and `openapi-root.json` (not the bundled file).

Regenerate the deploy/CI bundle:

```bash
python3 scripts/bundle_openapi.py
```

Writes `../openapi.json` (generated; prefer editing fragments here).
