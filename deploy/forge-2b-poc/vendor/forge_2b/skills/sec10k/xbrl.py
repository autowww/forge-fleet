"""Inline XBRL index (stdlib + regex). Facts keyed by concept and period for verification."""
from __future__ import annotations

import re
from html import unescape
from typing import Any

_ATTR_RE = re.compile(r'([\w:-]+)="([^"]*)"')
_IXBRL_FACT_RE = re.compile(r"<ix:nonFraction\b([^>]*)>([^<]*)</ix:nonFraction>", re.IGNORECASE)
_CONTEXT_RE = re.compile(r"<xbrli:context\b[^>]*id=\"([^\"]+)\"[^>]*>(.*?)</xbrli:context>", re.DOTALL | re.IGNORECASE)
_INSTANT_RE = re.compile(r"<xbrli:instant>([^<]+)</xbrli:instant>", re.IGNORECASE)
_STARTDATE_RE = re.compile(r"<xbrli:startDate>([^<]+)</xbrli:startDate>", re.IGNORECASE)
_ENDDATE_RE = re.compile(r"<xbrli:endDate>([^<]+)</xbrli:endDate>", re.IGNORECASE)
_UNIT_RE = re.compile(r"<xbrli:unit\b[^>]*id=\"([^\"]+)\"[^>]*>(.*?)</xbrli:unit>", re.DOTALL | re.IGNORECASE)
_MEASURE_RE = re.compile(r"<xbrli:measure>([^<]+)</xbrli:measure>", re.IGNORECASE)


def _parse_attrs(tag_body: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in _ATTR_RE.finditer(tag_body)}


def _parse_units(html: str) -> dict[str, str]:
    units: dict[str, str] = {}
    for match in _UNIT_RE.finditer(html):
        uid = match.group(1)
        measure = _MEASURE_RE.search(match.group(2))
        if measure:
            units[uid] = measure.group(1).split(":")[-1]
    return units


def _parse_contexts(html: str) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for match in _CONTEXT_RE.finditer(html):
        cid = match.group(1)
        body = match.group(2)
        instant = _INSTANT_RE.search(body)
        start = _STARTDATE_RE.search(body)
        end = _ENDDATE_RE.search(body)
        contexts[cid] = {
            "period_start": start.group(1).strip() if start else None,
            "period_end": (instant or end).group(1).strip() if (instant or end) else None,
            "is_instant": instant is not None,
        }
    return contexts


def _apply_scale(raw_value: float, attrs: dict[str, str]) -> float:
    scale = int(attrs.get("scale", "0") or "0")
    value = raw_value * (10**scale)
    if attrs.get("sign", "").strip() == "-":
        value = -abs(value)
    return value


def build_ixbrl_index(html: str) -> dict[str, Any]:
    """Return ``{"facts": [...], "by_concept_period": {(concept, period_end): [values...]}}``."""
    contexts = _parse_contexts(html)
    units = _parse_units(html)
    facts: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str | None], list[float]] = {}
    by_concept: dict[str, list[float]] = {}

    for match in _IXBRL_FACT_RE.finditer(html):
        attrs = _parse_attrs(match.group(1))
        concept = attrs.get("name", "")
        if not concept:
            continue
        short = concept.split(":")[-1]
        context_ref = attrs.get("contextRef", "")
        unit_ref = attrs.get("unitRef")
        raw_text = unescape(match.group(2)).replace(",", "").strip()
        if not raw_text:
            continue
        try:
            raw_value = float(raw_text)
        except ValueError:
            continue
        value = _apply_scale(raw_value, attrs)
        ctx = contexts.get(context_ref) or {}
        period_end = ctx.get("period_end")
        unit_slug = units.get(unit_ref or "", unit_ref or "")
        rec = {
            "concept": short,
            "full_name": concept,
            "value": value,
            "unit": unit_slug,
            "period_end": period_end,
            "period_start": ctx.get("period_start"),
            "context_ref": context_ref,
        }
        facts.append(rec)
        key = (short, period_end)
        by_key.setdefault(key, []).append(value)
        by_concept.setdefault(short, []).append(value)

    return {"facts": facts, "by_concept_period": by_key, "by_concept": by_concept, "contexts": contexts}
