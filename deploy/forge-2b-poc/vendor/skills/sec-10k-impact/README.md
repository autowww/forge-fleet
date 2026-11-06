# sec-10k-impact (forge-2b skill v1)

Declarative bundle for the SEC Form 10-K graph lane.

- `skill.yaml` — identifiers and file references
- `decision.schema.json` — JSON Schema for the atomic window decision (validated in Python)
- `prompt.system.md` — system prompt for the fixed-model call (categories must stay aligned with the schema enum)
- `etalon/` — FY24 NVDA slice for the skill scorer (`nvda-fy24-0001045810-24-000029.jsonl`)
- `taxonomy.yaml` — legacy category → `economic_family` / `economic_subtype`; optional subtype hints; US-GAAP concept hints for verification

Loaded at import time by [`src/forge_2b/skills/loader.py`](../../src/forge_2b/skills/loader.py).

**Path resolution:** `FORGE_2B_SKILL_DIR` may point at this folder; otherwise the loader searches upward for `skills/sec-10k-impact` (dev repo) or uses `/app/skills/sec-10k-impact` in the Fleet image.
