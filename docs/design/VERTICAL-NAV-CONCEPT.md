# Expandable vertical navigation concept

## Objective

Inside top-level pages, readers need local navigation without seeing every page in the entire site.

## Behavior

- Show only the current major section in the left rail.
- Current group is expanded by default.
- Other groups are collapsed and show a count.
- A section should fit in one viewport at 13-inch laptop height.
- `On this page` right rail shows only H2 headings for the current article.

## Desktop layout

```text
Top horizontal nav
--------------------------------------------------
Left local nav | Article content | On this page
```

## Mobile layout

```text
Top bar
[Section menu] [On this page]
Article content
```

## Local nav example

```text
Learn 101
  ▾ Start here
    What is Fleet?
    Install locally
    First job
  ▸ Studio and Admin (2)
  ▸ Troubleshooting (1)
```

## Accessibility

- Use `<button>` for disclosure controls, not clickable divs.
- Maintain `aria-expanded` and `aria-controls`.
- Preserve focus order.
- Escape closes dropdown/drawer where implemented.
- The current page link has `aria-current="page"`.
- The section nav is labelled with `aria-label="Learn 101 navigation"`.

## Acceptance

- Left nav does not exceed the viewport for common page sizes.
- No page exposes the full 50+ page site map in the default viewport.
- Keyboard navigation can expand/collapse groups.
- Active section and active page are visually clear.
