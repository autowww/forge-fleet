"""Exact-field comparison set for the Academy corpus.

Selects one T00 (or control) prompt per scenario that has a sealed exact key.
Scores the answer locally. The oracle is never part of the model request.
Human-review scenarios are recorded as NOT_SCORED.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from forge_squid.library_audit import _extract_object

_SKIP = {"ground_truth_type", "hard_gates", "reference_status", "label_source", "review_state", "kind", "role", "scenario_id", "variant", "level", "image_assets"}


def load_exact_oracles(academy: Path) -> dict[str, dict]:
    groups = academy / "inputs" / "trusted_evaluator" / "canonical" / "groups"
    found: dict[str, dict] = {}
    g01 = groups / "G01/evaluator/private_reference/expectations.json"
    if g01.is_file():
        for scenario, row in json.loads(g01.read_text(encoding="utf-8")).items():
            if "CLASSIFIER" in scenario and row.get("required_label"):
                found[scenario] = {"role": "classifier", "kind": "label", "label": row["required_label"]}
            elif "EXTRACTOR" in scenario and row.get("ground_truth_type") in {"exact_string", "exact_fields"}:
                fields = {key: value for key, value in row.items() if key not in _SKIP}
                if fields:
                    found[scenario] = {"role": "extractor", "kind": "fields", "fields": fields}
    g02 = groups / "G02/evaluator/expectations.json"
    if g02.is_file():
        for scenario, row in json.loads(g02.read_text(encoding="utf-8")).items():
            if "MEMORY_MANAGER" in scenario and row.get("action"):
                found[scenario] = {"role": "memory_manager", "kind": "memory", "oracle": row}
    g03 = groups / "G03/evaluator/oracles/g03_reference.json"
    if g03.is_file():
        for row in json.loads(g03.read_text(encoding="utf-8")):
            if row.get("role") == "planner" and row.get("kind") == "topological_order" and row.get("scenario_id"):
                found[row["scenario_id"]] = {
                    "role": "planner",
                    "kind": "topo",
                    "nodes": row.get("nodes") or [],
                    "edges": row.get("edges") or [],
                    "oracle_state": row.get("review_state"),
                }
    return found


def select_exact_prompts(cards: list[dict], oracles: dict[str, dict], student_roots: dict[str, Path]) -> list[dict]:
    """One prompt per exact scenario. Prefer technique T00 over a control file."""
    chosen: dict[str, dict] = {}
    for card in cards:
        scenario = str(card.get("scenario_id") or "")
        if scenario not in oracles or card.get("disposition") != "quality_probe":
            continue
        if card.get("technique_id") not in {None, "T00"} and card.get("lane") != "control":
            continue
        rank = 0 if card.get("technique_id") == "T00" else 1
        current = chosen.get(scenario)
        if current is not None and current["rank"] <= rank:
            continue
        student = student_roots.get(str(card.get("group")))
        if student is None:
            continue
        path = student / str(card.get("path"))
        if not path.is_file():
            continue
        chosen[scenario] = {
            "rank": rank,
            "id": card.get("id"),
            "group": card.get("group"),
            "scenario_id": scenario,
            "role": oracles[scenario]["role"],
            "kind": oracles[scenario]["kind"],
            "path": card.get("path"),
            "prompt": path.read_text(encoding="utf-8"),
        }
    return [value for _, value in sorted(chosen.items())]


def score_exact(kind: str, oracle: dict, text: str) -> dict:
    if kind == "label":
        return _score_label(oracle["label"], text)
    if kind == "fields":
        return _score_fields(oracle["fields"], text)
    if kind == "memory":
        return _score_memory(oracle["oracle"], text)
    if kind == "topo":
        return _score_topo(oracle, text)
    return {"pass": False, "reason": "unknown_kind"}


def _score_label(label: str, text: str) -> dict:
    obj = _extract_object(text)
    if obj is not None:
        actual = obj.get("category", obj.get("label", obj.get("required_label")))
        return {"pass": actual == label, "actual": actual, "expected": label}
    try:
        rows = list(csv.DictReader(io.StringIO(text.strip())))
    except csv.Error:
        return {"pass": False, "reason": "unparsed", "expected": label}
    if len(rows) != 1:
        return {"pass": False, "reason": "csv_rows", "expected": label}
    actual = (rows[0].get("category") or "").strip()
    return {"pass": actual == label, "actual": actual, "expected": label}


def _score_fields(fields: dict, text: str) -> dict:
    obj = _extract_object(text)
    if obj is None:
        return {"pass": False, "reason": "not_json", "expected": fields}
    mismatches = {}
    for key, value in fields.items():
        actual = obj.get(key, "MISSING")
        if str(actual) != str(value):
            mismatches[key] = {"actual": actual, "expected": value}
    return {"pass": not mismatches, "mismatches": mismatches}


def _score_memory(oracle: dict, text: str) -> dict:
    obj = _extract_object(text)
    if obj is None:
        return {"pass": False, "reason": "not_json"}
    ops = [op for op in (obj.get("proposed_operations") or []) if isinstance(op, dict)]
    action = str(oracle.get("action") or "").upper()
    key = str(oracle.get("key") or "").casefold()
    value = str(oracle.get("value") or "").casefold()
    matched = any(
        str(op.get("action") or "").upper() == action
        and str(op.get("key") or "").casefold() == key
        and str(op.get("value") or "").casefold() == value
        for op in ops
    )
    checks = {
        "simulated_only": obj.get("simulated_only") is True,
        "tool_execution": obj.get("tool_execution") == "NOT_RUN",
        "operation": matched,
    }
    return {"pass": all(checks.values()), "checks": checks}


def _score_topo(oracle: dict, text: str) -> dict:
    obj = _extract_object(text)
    if obj is None:
        return {"pass": False, "reason": "not_json"}
    steps = obj.get("ordered_steps")
    nodes = list(oracle.get("nodes") or [])
    if not isinstance(steps, list) or set(steps) != set(nodes) or len(steps) != len(set(steps)):
        return {"pass": False, "reason": "not_a_permutation", "actual": steps}
    index = {step: pos for pos, step in enumerate(steps)}
    ordered = all(index[edge[0]] < index[edge[1]] for edge in oracle.get("edges") or [] if len(edge) == 2)
    return {"pass": ordered, "actual": steps, "oracle_state": oracle.get("oracle_state")}


def citation_allowlist(cards: list[dict], oracles: dict[str, dict]) -> dict:
    """Scenarios a later report may cite, and whether an exact key exists."""
    rows = {}
    for card in cards:
        if card.get("disposition") != "quality_probe":
            continue
        if card.get("technique_id") not in {None, "T00"} and card.get("lane") != "control":
            continue
        scenario = str(card.get("scenario_id") or "")
        if not scenario or scenario.startswith("extra:"):
            continue
        current = rows.get(scenario)
        if current is not None and current.get("technique_id") == "T00":
            continue
        rows[scenario] = {
            "group": card.get("group"),
            "role": card.get("role"),
            "technique_id": card.get("technique_id"),
            "exact_key": scenario in oracles,
            "cite_as": "exact_field" if scenario in oracles else "shape_only",
        }
    return {
        "rule": "Cite a model-quality result only when cite_as is exact_field. shape_only cards name a contract; they do not carry an answer key.",
        "scenarios": len(rows),
        "exact_key": sum(1 for row in rows.values() if row["exact_key"]),
        "rows": rows,
    }


def human_review_ledger(cards: list[dict], academy: Path) -> dict:
    gates = {}
    path = academy / "inputs/trusted_evaluator/canonical/groups/G01/evaluator/private_reference/expectations.json"
    if path.is_file():
        for scenario, row in json.loads(path.read_text(encoding="utf-8")).items():
            if row.get("ground_truth_type") in {"rubric_pending", "source_grounded_rubric_pending"}:
                gates[scenario] = list(row.get("hard_gates") or [])
    seen = {}
    for card in cards:
        if card.get("disposition") != "human_review":
            continue
        scenario = str(card.get("scenario_id") or "")
        if not scenario or scenario in seen:
            continue
        seen[scenario] = {
            "group": card.get("group"),
            "role": card.get("role"),
            "status": "NOT_SCORED",
            "hard_gates": gates.get(scenario, []),
        }
    return {
        "rule": "These scenarios stay unscored until a person marks each hard gate. A model pick is not a verdict.",
        "scenarios": len(seen),
        "rows": seen,
    }
