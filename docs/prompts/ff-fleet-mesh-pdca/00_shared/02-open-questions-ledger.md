# Fleet Mesh — open questions ledger

Resolve or accept defaults before gating the listed phase.

| # | Question | Default assumption | Resolve before |
|---|----------|------------------|----------------|
| Q01 | Granite always mesh coordinator vs elected peer? | Phase 1: laptop router; Granite is worker fallback only | FM52 (coordinator ADR) |
| Q02 | GPU shared with Ollama/forge-llm on Granite? | Yes → static `gpu_reserved` on Granite (R25) | FM24 |
| Q03 | Laptop runs local batch when NAS+Granite saturated? | 503 unless `placement_policy: local_fallback` | FM12 |
| Q04 | Build context on remote worker: git pull vs upload bundle? | Git pull when `FLEET_GIT_ROOT` on worker; else migration bundle | FM10 |
| Q05 | Enroll token minted by Granite vs manual peer PUT? | Phase 1 manual `PUT /v1/remote-peers/*`; enroll API Phase 4 | FM14 |
| Q06 | Market Studio prod RPO/RTO targets? | TBD in R53 before Phase 5 gate | FM53 |
| Q07 | Apt suite: noble only or noble+jammy? | noble first; jammy when CI matrix ready | FM08 |
| Q08 | `forge-fleet-docker` installs Docker CE apt repo automatically? | Yes as optional `--with-docker` / `apt install forge-fleet-docker` | FM07 |
| Q09 | CDN auth for apt repo (public vs operator token)? | Public HTTPS read; write via CI secrets only | FM08 |
| Q10 | Both `forge-fleet` and `forge-fleet-user` on same host? | Discouraged; document port collision if both enabled | FM06 |

## Resolution log

| # | Resolved | Decision | Date |
|---|----------|----------|------|
| — | — | (none yet) | — |
