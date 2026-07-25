---
title: "Fleet as an Approved Execution Rail"
product: forge-fleet
hydration_source: forge-agentic-sdlc-standout-pack
---

# Fleet as an Approved Execution Rail

## Core Thesis

Fleet stands out as Forge's controlled execution rail: a small HTTP control plane for `docker_argv` jobs, templates, logs, telemetry, and operator-runbook automation on one Linux host.

The key idea is: **agents should not receive raw execution power by default. They should receive approved execution surfaces.**

## Condensed Thought

Agentic SDLC needs execution. Tests must run, audits must run, scripts must run, containers must run, and artifacts must be produced. But raw shell or Docker access is dangerous when handed to agents or remote automations.

Fleet gives Forge a pragmatic middle layer. It accepts JSON jobs, records them in SQLite, invokes Docker or Podman, handles optional workspace uploads, resolves container templates, tails stdout and stderr, and exposes an admin dashboard. It is explicitly an operator-controlled orchestrator, not a multi-tenant safe boundary by default.

## Why It Stands Out

The innovation is the practical risk posture. Forge does not pretend execution is safe just because it is wrapped in an AI workflow. Fleet's docs acknowledge that callers with job-submission power have serious authority on the host. The product boundary says agents should receive approved templates first, with raw job submission only if explicitly allowed.

This is a more realistic approach than giving agents unconstrained terminal access. It creates a path to useful automation while preserving operator control and reviewability.

## Forge Ecosystem Hooks

- **Fleet** owns controlled execution, templates, logs, and telemetry.
- **Lenses** can request or display approved job execution and evidence.
- **ApprovalRequest** gates execution authority.
- **Workcells** can use Fleet to perform bounded implementation or audit work.
- **EvidencePacket** can include FleetJobSummary, logs, artifacts, and quality gate results.
- **Blueprints** define when execution is needed and what evidence should result.

## Architecture Implications

A safe execution rail should include:

1. Template-first execution surfaces.
2. Bearer or loopback policy appropriate to deployment risk.
3. Clear trust boundary documentation.
4. Correlation between jobs and ForgeRun identifiers.
5. Logs and summaries suitable for evidence review.
6. Host-level operator runbooks and incident guidance.
7. Explicit refusal to treat the service as a default multi-tenant sandbox.
8. Optional raw execution only when policy and approval allow it.

Fleet should be close enough to Docker to be useful and constrained enough to be governable.

## Blog Post Seed Paragraph

Sooner or later, an agentic SDLC system has to run something. It may need tests, audits, builds, browser checks, or repository scripts. The unsafe version is simple: give the agent a shell and hope it behaves. Forge's Fleet takes a different path. It provides an operator-controlled HTTP control plane for Docker jobs and templates, designed to be correlated back to governed runs and reviewed through evidence. The result is not magic sandboxing. It is a practical execution rail with honest boundaries.

## Risks And Counterarguments

Fleet's power is also its risk. A host-level Docker execution service must be treated seriously. The docs should keep emphasizing operator control, template-first usage, bearer-token hygiene, network boundaries, and the difference between useful execution control and true sandbox isolation.

## Related

- [Start here](../01-start-here.md)
- [Forge Fleet README](../../README.md)
