# Workspace localization scope

**Canonical source:** edit this file only at the workspace root: `docs/WORKSPACE-LOCALIZATION-SCOPE.md` (relative to the multi-repo workspace that contains `blueprints/`, `forgesdlc/`, `forgesdlc-kitchensink/`, etc.).

**Copies:** the same filename is synced into each standalone git repository by `sync-workspace-localization-scope.sh` at the workspace root. Do **not** edit those copies by hand; change the canonical file, run the script, then commit **per repo**.

**Last updated:** 2026-04-06

---

## 1. Policy scope

1. **Geographic Europe — national / official languages** of European states. Sub-state **regional-only** locales (for example Catalan, Welsh, Basque, Scots Gaelic) are **out of scope** unless this document is amended with an explicit exception.
2. **Balkan languages — separate SKUs.** Bosnian, Croatian, Serbian, Slovenian, Albanian, Macedonian, and Montenegrin are **not** merged into a single Serbo-Croatian locale; each has its own row and translation memory.
3. **Baltic languages — separate SKUs.** Estonian, Latvian, and Lithuanian are always three distinct locales.
4. **Ukrainian** is in scope (`uk`). **Russian** and **Belarusian** are **not** in scope for any product SKU (no `ru*`, no `be*`).
5. **Extended locales (policy):** Turkish, Hebrew, and a **single** Arabic SKU (`ar`) are supported alongside European locales.
6. **Andorra** has only Catalan as official; Catalan is treated as regional-only here. For Andorra users, default to **Spanish** or **French** product locales until an exception is added.

---

## 2. Excluded language tags

| Tag pattern | Reason |
|-------------|--------|
| `ru`, `ru-RU`, … | Policy: Russian not supported |
| `be`, `be-BY`, … | Policy: Belarusian not supported |

Do not ship store listings, in-app resources, or static site trees for these tags.

---

## 3. RTL and complex scripts

| Tag | Direction | Notes |
|-----|-----------|--------|
| `he`, `he-IL` | RTL | Full layout mirroring, bidi, icon direction, QA pass |
| `ar` | RTL | Same as Hebrew for UI chrome |
| `el` | LTR | Greek script |
| `bg`, `mk`, `sr`, `uk`, … | LTR | Cyrillic; watch line length and fonts |

Turkish (`tr`, `tr-TR`) is LTR but uses dotted capital **İ**; sorting and search must be locale-aware.

---

## 4. Arabic (single SKU)

- **Standard tag:** `ar` (generic; MSA-oriented for formal UI copy).
- **Policy:** one Arabic locale for the workspace unless this file is revised. National variants (`ar-SA`, `ar-EG`, …) are out of scope until explicitly added.

---

## 5. Montenegrin vs Serbian

| Language | Preferred BCP-47 | Notes |
|----------|-------------------|--------|
| Montenegrin | `cnr` | ISO 639-3; use where the platform supports it |
| Fallback | `sr-Latn-ME` | Some stacks lack `cnr`; document product-specific choice |

Android resource qualifiers may differ from web `hreflang`; align per platform in implementation guides.

---

## 6. Master locale table (supported SKUs)

Primary tags are **BCP-47**. Where a country variant matters for stores or legal copy, a more specific subtag may be used in implementation; the **language** row still counts as one workspace SKU.

### Western, northern, and southern Europe

| Language | Primary tag(s) | Notes |
|----------|----------------|-------|
| English | `en`, `en-GB` | UK, Ireland (English), Malta (with `mt`) |
| Irish | `ga` | Ireland co-official |
| French | `fr` | FR, BE, CH, LU, MC, etc. |
| German | `de` | DE, AT, LI; `de-CH` in CH |
| Dutch | `nl` | NL, BE |
| Luxembourgish | `lb` | LU |
| Maltese | `mt` | MT |
| Greek | `el` | GR, CY |
| Spanish | `es` | ES |
| Portuguese | `pt` | PT |
| Italian | `it` | IT, CH (`it-CH`), SM, VA |
| Icelandic | `is` | IS |
| Norwegian Bokmål | `nb` | NO |
| Norwegian Nynorsk | `nn` | NO (separate SKU from `nb`) |
| Swedish | `sv` | SE |
| Danish | `da` | DK |
| Finnish | `fi` | FI |

### Central and eastern Europe (non-Balkan list below)

| Language | Primary tag(s) | Notes |
|----------|----------------|-------|
| Polish | `pl` | PL |
| Czech | `cs` | CZ |
| Slovak | `sk` | SK |
| Hungarian | `hu` | HU |
| Romanian | `ro` | RO, MD |
| Bulgarian | `bg` | BG |

### Balkan (separate SKUs)

| Language | Primary tag(s) | Notes |
|----------|----------------|-------|
| Bosnian | `bs` | BA |
| Croatian | `hr` | HR |
| Serbian | `sr` | RS; script variants (`sr-Cyrl`, `sr-Latn`) per product |
| Slovenian | `sl` | SI |
| Albanian | `sq` | AL, XK |
| Macedonian | `mk` | MK |
| Montenegrin | `cnr` | ME; see §5 |

### Baltic (separate SKUs)

| Language | Primary tag(s) | Notes |
|----------|----------------|-------|
| Estonian | `et` | EE |
| Latvian | `lv` | LV |
| Lithuanian | `lt` | LT |

### Other Europe

| Language | Primary tag(s) | Notes |
|----------|----------------|-------|
| Ukrainian | `uk` | UA |

### Extended (non-European policy)

| Language | Primary tag(s) | Notes |
|----------|----------------|-------|
| Turkish | `tr`, `tr-TR` | TR; also official in CY |
| Hebrew | `he`, `he-IL` | IL; RTL |
| Arabic | `ar` | RTL; single SKU (§4) |

---

## 7. i18n and l10n standards (workspace)

1. **Identifiers:** use **BCP-47** tags consistently (APIs, filenames, config).
2. **Excluded locales:** never ship `ru*` or `be*` for this workspace’s products.
3. **Dynamic strings:** use ICU-style placeholders (`{name}`, plural rules) in Android, Python, and TS as appropriate; do not concatenate translated fragments for grammar.
4. **Static sites:** when multiple languages exist, use stable URLs and **`hreflang`** alternates for equivalent pages.
5. **Stores and marketing:** store listing locales may differ from in-app first ship; still must not use excluded tags.
6. **QA:** RTL (`he`, `ar`) requires a dedicated pass; Cyrillic and Greek need font and overflow checks.

---

## 8. Approximate locale count

- **Western / northern / southern (table §6.1):** 16 language rows (English counts as one policy row; `en-GB` is a variant).
- **Central / eastern (§6.2):** 6.
- **Balkan (§6.3):** 7.
- **Baltic (§6.4):** 3.
- **Other Europe (§6.5):** 1.
- **Extended (§6.6):** 3.

**Rough total:** about **36 named language SKUs** (plus regional variants like `en-GB` / `de-CH` where products require them). Use this for TMS sizing and budgeting, not as a hard cap on resource-qualifier explosion per platform.

---

## 9. Propagation

After editing the canonical file:

```bash
./sync-workspace-localization-scope.sh
```

Commit the updated `WORKSPACE-LOCALIZATION-SCOPE.md` in **each** repository that received a copy (one commit per repo).

This duplicated file is an intentional **workspace policy** exception to “single source of truth” for Markdown in other contexts: each repo must carry the same SKU list for implementers without submodule pull order dependencies.
