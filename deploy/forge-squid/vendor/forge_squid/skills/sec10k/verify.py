"""Match observations against an iXBRL index (VERIFIED | UNVERIFIED | CONTRADICTED)."""
from __future__ import annotations

import re
from typing import Any

_REL_TOL = 0.02  # 2% relative for scaled millions


def _concept_for_subtype(taxonomy: dict[str, Any], subtype: str) -> str | None:
    m = taxonomy.get("xbrl_concepts") or {}
    return m.get(subtype)


def _period_end_for_fy(html: str, fiscal_year: str | None) -> str | None:
    if not fiscal_year or not html:
        return None
    # NVDA-style: year end in Jan → "Jan XX, 20YY" in contexts
    yy = fiscal_year[-2:]
    pat = rf"Jan\s+\d{{1,2}},\s*20{yy}"
    m = re.search(pat, html, re.I)
    if m:
        return m.group(0).replace(",", "").replace("  ", " ")
    return None


def _find_near(target: float, candidates: list[float]) -> bool:
    if not candidates:
        return False
    for c in candidates:
        if target == 0:
            if abs(c) < 1e-9:
                return True
            continue
        if abs(c - target) / max(abs(target), abs(c), 1.0) <= _REL_TOL:
            return True
    return False


def verify_observation(obs: dict[str, Any], ix: dict[str, Any], *, raw_html: str, taxonomy: dict[str, Any]) -> dict[str, Any]:
    if obs.get("_change_column"):
        return {
            "status": "CONTRADICTED",
            "reason": "change_or_percent_column",
            "concept": None,
        }

    values = obs.get("values") or []
    if not values:
        return {"status": "UNVERIFIED", "reason": "no_numeric", "concept": None}

    concept = _concept_for_subtype(taxonomy, str(obs.get("economic_subtype") or ""))
    if not concept:
        return {"status": "UNVERIFIED", "reason": "no_concept_map", "concept": None}

    period = obs.get("period") or {}
    fy = period.get("fiscal_year")
    period_end = period.get("period_end") or _period_end_for_fy(raw_html, str(fy) if fy else None)

    by_cp = ix.get("by_concept_period") or {}
    v0 = values[0]
    raw_val = float(v0["value"])
    unit = str(v0.get("unit", "")).lower()

    # Scale: filing often in millions; statement may say "billion"
    target = raw_val
    if "billion" in unit and raw_val < 1e6:
        target = raw_val * 1e9
    elif "million" in unit and raw_val < 1e3:
        target = raw_val * 1e6

    matched: list[float] = []
    if period_end:
        matched.extend(by_cp.get((concept, period_end)) or [])
    if not matched:
        matched.extend(ix.get("by_concept", {}).get(concept) or [])
    if not matched:
        for (c, _), nums in by_cp.items():
            if c == concept:
                matched.extend(nums)

    if _find_near(target, matched):
        return {"status": "VERIFIED", "reason": "xbrl_match", "concept": concept, "period_end": period_end}

    if matched:
        return {"status": "CONTRADICTED", "reason": "numeric_mismatch", "concept": concept, "xbrl_values": matched[:5]}

    return {"status": "UNVERIFIED", "reason": "no_xbrl_fact", "concept": concept}
