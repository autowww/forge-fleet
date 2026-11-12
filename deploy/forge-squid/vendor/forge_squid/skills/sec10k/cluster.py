"""Fact dedup and theme clusters (deterministic)."""
from __future__ import annotations

import json
import re
from typing import Any


def _norm_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9.%$]+", text.lower()) if len(t) > 2}


def _period_key(period: dict[str, Any]) -> str:
    if not period:
        return ""
    return json.dumps(period, sort_keys=True)


def _value_key(obs: dict[str, Any]) -> str:
    vals = obs.get("values") or []
    if not vals:
        return ""
    v0 = vals[0]
    return f"{v0.get('value')}:{v0.get('unit')}"


def dedupe_key(obs: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(obs.get("economic_family") or ""),
        str(obs.get("economic_subtype") or ""),
        _period_key(obs.get("period") or {}),
        _value_key(obs),
    )


def _overlap_subclusters(members: list[dict[str, Any]], *, jac_min: float = 0.28) -> list[list[dict[str, Any]]]:
    """Split a (family, subtype) bucket into theme lines: greedy clusters by Jaccard vs canonical."""
    members = sorted(members, key=lambda o: (-int(o.get("composite", 0)), str(o.get("text", ""))))
    clusters: list[list[dict[str, Any]]] = []
    for obs in members:
        toks = _norm_tokens(str(obs.get("text", "")))
        placed = False
        for cl in clusters:
            canon = cl[0]
            ct = _norm_tokens(str(canon.get("text", "")))
            if not toks or not ct:
                cl.append(obs)
                placed = True
                break
            j = len(toks & ct) / max(1, len(toks | ct))
            if j >= jac_min:
                cl.append(obs)
                placed = True
                break
        if not placed:
            clusters.append([obs])
    return clusters


def cluster_and_rank(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe identical (family, subtype, period, value); theme sub-clusters; sort by composite."""
    by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for obs in observations:
        k = dedupe_key(obs)
        cur = by_key.get(k)
        if cur is None or int(obs.get("composite", 0)) > int(cur.get("composite", 0)):
            by_key[k] = obs

    deduped = list(by_key.values())
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for obs in deduped:
        gk = (str(obs.get("economic_family")), str(obs.get("economic_subtype")))
        groups.setdefault(gk, []).append(obs)

    out: list[dict[str, Any]] = []
    for (_, _), members in sorted(groups.items(), key=lambda x: x[0]):
        for sub_i, sub_members in enumerate(_overlap_subclusters(members)):
            sub_members.sort(key=lambda o: (-int(o.get("composite", 0)), str(o.get("text", ""))))
            canonical = sub_members[0]
            cid = f"{canonical.get('economic_family')}.{canonical.get('economic_subtype')}.{sub_i}"
            for i, m in enumerate(sub_members):
                m["cluster_id"] = cid
                m["cluster_canonical"] = i == 0
                m["cluster_members"] = len(sub_members)
                if i == 0:
                    m["cluster_snippet"] = m.get("text", "")[:120]
                out.append(m)

    out.sort(key=lambda o: (-int(o.get("composite", 0)), o.get("cluster_id", ""), str(o.get("text", ""))))
    return out
