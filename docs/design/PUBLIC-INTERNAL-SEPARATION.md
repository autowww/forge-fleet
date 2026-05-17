# Public vs internal documentation separation

## Current issue

Fleet currently exposes Maintainer pages in primary navigation. These pages are valuable but distract public readers and dilute enterprise trust when they appear beside Learn, Build, Operate, and Reference.

## Rule

Public readers should see paths that help them evaluate, adopt, integrate, operate, or reference Fleet. Maintainer docs should be findable but not prominent.

## Public categories

- Start
- Learn
- Build
- Operate
- Reference
- Examples
- Changelog
- Troubleshooting

## Internal/maintainer categories

- UX workflow prompts (internal planning)
- Site generator notes
- Screenshot workflow
- Docs contracts
- Visual coverage tracking
- Admin UI design notes
- Release checklists

## Navigation treatment

- Put Maintainers under `More`.
- Add a clear label: `Maintainers — internal/public transparency`.
- Exclude Maintainers from top hero path cards.
- Exclude Maintainers from beginner and practitioner route choices.
- Keep direct URLs working.

## Page treatment

Every maintainer page should start with:

```markdown
> Maintainer-facing: this page is published for transparency. Product users usually want Start, Learn, Build, Operate, or Reference.
```
