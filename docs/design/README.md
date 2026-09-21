# Fleet design concepts

## Fleet Mesh PDCA program

Multi-host Fleet mesh (federated nodes, apt operator install, Class A batch placement, resource planning, stateful/DR). Requirements and phase sequence:

- [ff-fleet-mesh-pdca](../prompts/ff-fleet-mesh-pdca/00-master-sequence.md)
- [Requirements ledger](../prompts/ff-fleet-mesh-pdca/00_shared/00-requirements-ledger.md)
- [Assumptions and bootstrap](../prompts/ff-fleet-mesh-pdca/00_shared/01-assumptions-and-non-goals.md)
- Gate: `./scripts/ff-fleet-mesh-pdca/check-phase-gate.sh FM00`

Related: [Granite operator boundary](granite-operator-boundary.md) (mesh ops remain Fleet HTTP only).

---

## Fleet UX design concepts

These files preserve the UX direction for the Fleet documentation refactor. Keep them in the repository under `docs/design/` or `docs/maintainers/ux/` so future documentation changes do not drift back into a flat handbook index.

Recommended target location in the Fleet repo:

```text
docs/design/
  UX-SCORECARD.md
  NAVIGATION-CONCEPT.md
  PAGE-LAYOUT-CONCEPT.md
  CONTENT-CHUNKING-CONCEPT.md
  HERO-SECTIONS-CONCEPT.md
  KS-COMPONENTS-CONCEPT.md
  IA-MAP.md
  VERTICAL-NAV-CONCEPT.md
  VISUAL-LANGUAGE.md
```

- **[`VISUAL-LANGUAGE.md`](VISUAL-LANGUAGE.md)** — author-facing visual/tone guidance for Fleet docs

Use these concepts as design contracts.
