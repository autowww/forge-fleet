#!/usr/bin/env python3
"""Validate infra-flows/*.lmeta against confirm-gate and atom catalog contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOWS_DIR = ROOT / "infra-flows"

REGISTERED_ATOMS = {
    "infra_pg_dump",
    "infra_pg_table_counts",
    "infra_pg_schema_version",
    "infra_migrate_plan",
    "infra_migrate_run",
    "infra_compose_restart",
    "infra_compose_deploy",
    "infra_confirm_gate",
    "infra_root_escalation",
    "infra_smoke_test",
    "infra_emit_progress",
    "infra_audit",
}

WRITE_ATOMS = {
    "infra_migrate_run",
    "infra_compose_restart",
    "infra_compose_deploy",
}

FORBIDDEN_KEYS = ("argv", "shell", "rm ", "DROP TABLE")


def _collect_task_ids(state: dict) -> list[str]:
    ids: list[str] = []
    for action in state.get("actions") or []:
        fn = action.get("functionRef") or {}
        args = fn.get("arguments") or {}
        if fn.get("refName") == "forgeLcdlRun":
            tid = str(args.get("task_id") or "").strip()
            if tid:
                ids.append(tid)
        elif fn.get("refName") in ("forgeBranch", "forgeTryCatch"):
            for slot in ("then", "else", "try", "catch"):
                slot_val = args.get(slot)
                if isinstance(slot_val, dict) and slot_val.get("task_id"):
                    ids.append(str(slot_val["task_id"]))
    return ids


def _walk_states(flow: dict) -> list[tuple[str, list[str]]]:
    states = flow.get("states") or []
    by_name = {str(s.get("name")): s for s in states if isinstance(s, dict) and s.get("name")}
    start = str(flow.get("start") or "")
    order: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    current = start
    while current and current not in seen:
        seen.add(current)
        state = by_name.get(current) or {}
        order.append((current, _collect_task_ids(state)))
        if state.get("end"):
            break
        current = str(state.get("transition") or state.get("defaultTransition") or "")
    return order


def validate_flow(path: Path) -> list[str]:
    errors: list[str] = []
    raw = path.read_text(encoding="utf-8")
    for token in FORBIDDEN_KEYS:
        if token in raw and token in ('"argv"', '"shell"'):
            errors.append(f"{path.name}: forbidden key pattern {token}")
    try:
        flow = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"{path.name}: invalid JSON: {exc}"]
    if not isinstance(flow, dict):
        return [f"{path.name}: root must be object"]

    saw_confirm = False
    for _name, task_ids in _walk_states(flow):
        for tid in task_ids:
            if tid not in REGISTERED_ATOMS:
                errors.append(f"{path.name}: unknown task_id {tid}")
            if tid == "infra_confirm_gate":
                saw_confirm = True
            if tid in WRITE_ATOMS and not saw_confirm:
                errors.append(f"{path.name}: write task {tid} before any infra_confirm_gate in linear path")
    return errors


def main() -> int:
    paths = sorted(FLOWS_DIR.glob("*.lmeta"))
    if not paths:
        print("no flows found", file=sys.stderr)
        return 1
    all_errors: list[str] = []
    for path in paths:
        all_errors.extend(validate_flow(path))
    if all_errors:
        for err in all_errors:
            print(err, file=sys.stderr)
        return 1
    print(f"ok: {len(paths)} infra flow(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
