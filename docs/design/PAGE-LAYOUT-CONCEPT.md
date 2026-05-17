# Fleet page layout concept

## Layout stack

Every public page should use one of these layout types.

### 1. Product landing page

Used for `/`.

```text
Hero
  Title, one-line value proposition, 2-3 CTAs, product visual/diagram
Trust/value strip
  single-host, SQLite ledger, Docker runner, admin dashboard
Choose your path cards
Architecture in 60 seconds
Common scenarios
Footer CTA
```

### 2. Section hub

Used for Start, Learn, Build, Operate, Reference, Examples.

```text
Section hero
  outcome, audience, CTA
Path cards, max 6
Recommended sequence
Featured diagram or comparison
Frequently used links
Next section CTA
```

### 3. Tutorial page

Used for 101 and guided 201 tasks.

```text
Context card
  Goal, Audience, Time, Prereqs, Output
Steps
  3-7 numbered steps
Verify
  commands and expected results
Troubleshoot
  3-5 symptom cards
Next
  one primary next page, one reference link
```

### 4. Recipe page

Used for Examples and integration guides.

```text
Use when / Avoid when
Inputs
Minimal example
Annotated example
Verify
Variants
Related API/schema links
```

### 5. Reference page

Used for API, schemas, env, errors.

```text
Reference hero
Filter/search affordance if generated HTML supports it
Grouped sections
Method/route cards
Request/response schema links
Examples collapsed by default
```

### 6. Enterprise operation page

Used for security, observability, backup, incident response.

```text
Operational objective
Trust boundaries / risk box
Checklist
Runbook steps
Signals and thresholds
Rollback / escalation
Evidence to collect
```

## Layout rules

- Top-level pages must not be long articles.
- Put deep details behind child pages or collapsible details.
- Use prose for orientation, cards for choices, tables for comparisons, code for actions.
- Keep a section hub under 900 words.
- Keep a tutorial under 1200 words. Split when larger.
- Keep headings descriptive and human-facing.
- Prefer `What Fleet does` over `Overview`.
- Prefer `Run your first job` over `Job lifecycle` for learning paths.
