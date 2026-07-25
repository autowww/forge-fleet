# Workspace abbreviations — maintainer README

| Path | Role |
|------|------|
| `catalog.yaml` | Source of truth for terms and bridges |
| `terms/*.md` | Generated per-term handbook pages |
| `bridges/*.md` | Generated collision guides |
| `../WORKSPACE-ABBREVIATIONS.md` | Generated hub index |

## Regenerate

```bash
python3 scripts/generate-workspace-abbreviations.py
./sync-workspace-abbreviations.sh
```

Then rebuild **forgesdlc** and **blueprints-website** per `auto-build-sites.mdc`.

Term count: **88** · Bridges: **8**
