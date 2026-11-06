"""Map legacy window decisions to forge-market-shaped observations (+ column / period hints)."""
from __future__ import annotations

import re
from typing import Any

_MONEY = re.compile(
    r"(?P<num>-?\$?\s?\d[\d,]*(?:\.\d+)?)\s*(?P<unit>billion|million|thousand|%|percent)?",
    re.I,
)
_DATE_FY = re.compile(r"\bFY\s*20(\d{2})\b", re.I)
_FISCAL_YEAR_WORD = re.compile(r"\bfiscal year\s*20(\d{2})\b", re.I)
_DATE_MON = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2},\s*20(\d{2})\b",
    re.I,
)


def _coerce_float(x: Any) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    s = str(x).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s.replace("$", "").replace("%", ""))
    except ValueError:
        return None


def _materiality_from_impact(impact: int) -> int:
    if impact >= 5:
        return 5
    if impact >= 3:
        return 3
    return 1


def _fiscal_year_from_period(period: dict[str, Any] | str | None, text: str) -> str | None:
    if isinstance(period, dict):
        fy = period.get("fiscal_year") or period.get("fy")
        if isinstance(fy, str) and re.match(r"20\d{2}", fy):
            return fy
        if isinstance(fy, int):
            if fy < 100:
                return f"20{fy:02d}"
            return str(fy)
    if isinstance(period, str):
        m = _DATE_FY.search(period) or _FISCAL_YEAR_WORD.search(period)
        if m:
            return "20" + m.group(1) if len(m.group(1)) == 2 else m.group(0)[-4:]
    m = _DATE_FY.search(text) or _FISCAL_YEAR_WORD.search(text)
    if m:
        yy = m.group(1)
        return f"20{yy}" if len(yy) == 2 else yy
    m = _DATE_MON.search(text)
    if m:
        # NVDA FY ends late Jan: date in Jan-Feb -> FY label = year of that date
        mon, yy = m.group(1).lower(), m.group(2)
        return f"20{yy}"
    return None


def _change_column_hint(text: str) -> bool:
    t = text.lower()
    return "| $change:" in t or "| %change:" in t or "$change:" in t and "|" in text


def _parse_value_unit(stmt: dict[str, Any], text: str) -> tuple[float | None, str, str]:
    """Return (numeric value, unit slug, role)."""
    role = str(stmt.get("value_role") or "reported")
    val = _coerce_float(stmt.get("value"))
    unit = str(stmt.get("unit") or "").strip() or "unspecified"
    if val is not None:
        return val, unit, role
    m = _MONEY.search(text)
    if not m:
        return None, "unspecified", role
    raw = m.group("num").replace("$", "").replace(",", "").strip()
    try:
        val = float(raw)
    except ValueError:
        return None, "unspecified", role
    u = (m.group("unit") or "").lower()
    if u in ("%", "percent"):
        unit = "percent"
    elif u in ("billion", "million", "thousand"):
        unit = f"USD {u}"
    else:
        unit = "unspecified"
    return val, unit, role


def map_legacy_to_observation(stmt: dict[str, Any], taxonomy: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(str(stmt.get("text", "")).split())
    cat = str(stmt.get("category") or "OTHER").upper()
    impact = int(stmt.get("impact") or 3)
    legacy_map = taxonomy.get("legacy_category") or {}
    base = legacy_map.get(cat) or legacy_map.get("OTHER") or {
        "economic_family": "GEN.OTHER",
        "economic_subtype": "UNSPECIFIED",
    }
    fam = str(base.get("economic_family", "GEN.OTHER"))
    sub = str(base.get("economic_subtype", "UNSPECIFIED"))

    hint = str(stmt.get("subtype_hint") or "").lower()
    hay = f"{hint} {text.lower()}"
    for row in taxonomy.get("subtype_hints") or []:
        kws = row.get("keywords") or []
        if any(k in hay for k in kws):
            fam = str(row.get("economic_family", fam))
            sub = str(row.get("economic_subtype", sub))
            break

    period_in = stmt.get("period")
    period_dict: dict[str, Any] = {}
    if isinstance(period_in, dict):
        period_dict = {k: v for k, v in period_in.items() if v is not None}
    elif isinstance(period_in, str) and period_in.strip():
        period_dict = {"label": period_in.strip()}

    fy = _fiscal_year_from_period(period_dict if period_dict else None, text)
    if fy and "fiscal_year" not in period_dict:
        period_dict["fiscal_year"] = fy

    smode = str(stmt.get("statement_mode") or "actual").lower()
    if smode not in ("actual", "guidance", "intent"):
        smode = "actual"

    val, unit, role = _parse_value_unit(stmt, text)
    values: list[dict[str, Any]] = []
    if val is not None:
        values.append({"value": val, "unit": unit, "role": role})

    eq: list[str] = []
    if text:
        eq.append(text[:240])
    change_col = _change_column_hint(text)

    return {
        "text": text,
        "category": cat,
        "impact": impact,
        "economic_family": fam,
        "economic_subtype": sub,
        "statement_mode": smode,
        "period": period_dict,
        "values": values,
        "evidence_quotes": eq,
        "materiality_weight": _materiality_from_impact(impact),
        "_change_column": change_col,
        "_legacy_category": cat,
    }
