"""Rules-only instrument audit for the Forge Model Academy prompt corpus.

One card per stored prompt. The card says which quality claim that prompt
can support. A Qwen call is queued only when the contract section has no
shape the rules can name. The model never assigns the disposition.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PACKS = (
    ("G01", "G01/student", "groups/G01-understanding/manifest.jsonl"),
    ("G02", "G02/student", "groups/G02-knowledge-perception/manifest.jsonl"),
    ("G03", "G03/student", "groups/G03-reasoning-governance/manifest.jsonl"),
    ("G04", "G04/student", "groups/G04-software-engineering/manifest.jsonl"),
    ("G05", "G05/student", "groups/G05-execution-orchestration/manifest.jsonl"),
    ("G06", "G06/student", "groups/G06-security-media/manifest.jsonl"),
    ("G07", "G07/student", "groups/G07-cross-role/manifest.jsonl"),
)

VALIDATORS = {
    "G01": "tools/validate_g01_matrix.py",
    "G02": "tools/validate_g02_matrix.py",
    "G03": "tools/validate_g03_matrix.py",
    "G04": "tools/validate_g04_matrix.py",
    "G05": "tools/validate_g05_matrix.py",
    "G06": "tools/validate_g06_matrix.py",
    "G07": "tools/validate_g07_matrix.py",
}

LANE_DIRS = ("control_prompts", "strategy_prompts", "controls", "strategy")
LEAK_TOKENS = ("ground_truth_type", "required_label", "private_reference", "Fit: NEGATIVE_CONTROL")
HUMAN_ROLES = frozenset({"clarifier", "comprehender", "critic", "reviewer", "architect", "evaluator", "summarizer"})
EXACT_ROLES = frozenset({"classifier", "extractor", "memory_manager"})
PICKS = ("json_object", "csv_row", "prose_only", "none")

_HEADING = re.compile(r"(?m)^##\s+(.+?)\s*$")
_BOLD_CONTRACT = re.compile(r"(?im)^\*\*(?:required response|output contract|required output):?\*\*\s*:?\s*")
_JSON_WORD = re.compile(r"\bJSON\b")
_CSV_WORD = re.compile(r"\bCSV\b|comma-separated", re.I)
_QUOTED_KEY = re.compile(r'"[A-Za-z_][A-Za-z0-9_]*"\s*:')
_PROSE = re.compile(r"\b(paragraph|sentences|prose|ranked list|questions?)\b", re.I)
_STRATEGY = re.compile(
    r"technique choice, not the task|do not solve the task|without solving|independent method selection|"
    r"independent strategy-selection|strategy selector|prompting-strategy selection|least-cost sufficient|"
    r"solve the operational scenario",
    re.I,
)


def academy_groups(root: Path) -> Path:
    return root / "inputs" / "student" / "canonical" / "groups"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def contract_section(text: str) -> str | None:
    headings = list(_HEADING.finditer(text))
    for index, match in enumerate(headings):
        title = match.group(1).lower()
        if "output" in title or "response object" in title:
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            return text[match.end():end]
    bold = _BOLD_CONTRACT.search(text)
    if bold is None:
        return None
    lines = text[bold.end():].splitlines()
    kept: list[str] = []
    for line in lines:
        if line.startswith("## ") or line.startswith("**") or line.startswith("---"):
            break
        kept.append(line)
    return "\n".join(kept)


def shape_of(section: str | None) -> str:
    """Name the contract shape. ``unknown`` is the only shape that may be queued."""
    if section is None:
        return "missing"
    body = section.strip()
    if not body:
        return "missing"
    has_json = bool(_JSON_WORD.search(body) or "{" in body or _QUOTED_KEY.search(body))
    has_csv = bool(_CSV_WORD.search(body))
    if has_json and has_csv:
        return "mixed"
    if has_json:
        return "json_object"
    if has_csv:
        return "csv_row"
    if _PROSE.search(body):
        return "prose_only"
    return "unknown"


def attachment_paths(record: dict) -> list[str]:
    raw = record.get("attachments")
    if isinstance(raw, dict):
        return [str(path) for path in raw]
    if isinstance(raw, list):
        return [str(path) for path in raw]
    hashed = record.get("attachment_sha256")
    if isinstance(hashed, dict):
        return [str(path) for path in hashed]
    return []


def assess_text(text: str, *, role: str, group: str, technique_fit: str | None, lane: str, needs_vision: bool) -> dict:
    """Classify one prompt body. Hash and file existence are applied by the caller."""
    issues: list[str] = []
    for token in LEAK_TOKENS:
        if token in text:
            issues.append(f"leakage:{token}")
    section = contract_section(text)
    shape = shape_of(section)
    strategy = lane == "strategy"
    if strategy and not _STRATEGY.search(text):
        issues.append("strategy_heading_missing")
    modality = needs_vision or role == "vision_analyst" or "T15" == technique_fit
    # technique id is not the fit; callers pass fit separately and set modality from the id.
    disposition = _disposition(role, group, shape, technique_fit, strategy, issues, modality)
    return {
        "shape": shape,
        "strategy": strategy,
        "issues": issues,
        "disposition": disposition,
        "usable_for": _usable(disposition),
        "blocked_claims": _blocked(disposition),
        "contract_excerpt": (section or "").strip()[:1200],
    }


def _disposition(role: str, group: str, shape: str, technique_fit: str | None, strategy: bool, issues: list[str], modality: bool) -> str:
    if any(item.startswith("leakage:") or item == "strategy_heading_missing" for item in issues):
        return "hold_broken"
    if strategy:
        return "strategy_selector"
    if shape in {"missing", "unknown", "mixed"}:
        return "needs_binding"
    if technique_fit == "NEGATIVE_CONTROL":
        return "negative_control"
    if modality:
        return "confounded_modality"
    if role in EXACT_ROLES:
        return "quality_probe"
    if role == "planner" and shape == "json_object":
        return "quality_probe"
    if role in HUMAN_ROLES:
        return "human_review"
    if group in {"G04", "G05", "G06", "G07"} or shape in {"json_object", "csv_row", "prose_only"}:
        return "structural_gate"
    return "needs_binding"


def _usable(disposition: str) -> list[str]:
    return {
        "quality_probe": ["exact_field"],
        "structural_gate": ["format_compliance"],
        "human_review": ["human_rubric"],
        "confounded_modality": ["modality_blocked"],
        "negative_control": ["abstention_only"],
        "strategy_selector": ["technique_choice"],
    }.get(disposition, [])


def _blocked(disposition: str) -> list[str]:
    if disposition == "quality_probe":
        return ["technique_effect", "modality", "execution_truth"]
    if disposition == "structural_gate":
        return ["role_skill", "model_is_smarter", "execution_truth"]
    return ["model_is_smarter", "role_skill"]


def verify_binding(raw: str, section: str) -> dict:
    """Accept a model pick only when the contract text independently supports it."""
    obj = _extract_object(raw)
    if obj is None or ("pick" not in obj and "shape" not in obj):
        return {"accepted": False, "reason": "not_json", "pick": None}
    pick = obj.get("pick", obj.get("shape"))
    if pick not in PICKS:
        return {"accepted": False, "reason": "fabricated_pick", "pick": pick}
    supported = _supported_picks(section)
    if pick not in supported:
        return {"accepted": False, "reason": "unsupported_pick", "pick": pick, "supported": sorted(supported)}
    return {"accepted": True, "reason": "text_supports_pick", "pick": pick}


def _supported_picks(section: str) -> set[str]:
    body = section or ""
    found = {"none"} if not body.strip() else set()
    if _JSON_WORD.search(body) or "{" in body or _QUOTED_KEY.search(body):
        found.add("json_object")
    if _CSV_WORD.search(body):
        found.add("csv_row")
    if _PROSE.search(body):
        found.add("prose_only")
    if not found:
        found.add("none")
    return found


def _extract_object(raw: str) -> dict | None:
    text = raw or ""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _lane_of(relative: str, record: dict) -> str:
    kind = str(record.get("kind") or "")
    if "strategy" in relative or kind == "strategy":
        return "strategy"
    if "control" in relative or kind in {"baseline", "control"}:
        return "control"
    return "technique"


def _modality(record: dict, relative: str) -> bool:
    if record.get("needs_vision") is True:
        return True
    if record.get("role") == "vision_analyst":
        return True
    if "/T15/" in f"/{relative}" or record.get("technique_id") == "T15":
        return True
    images = record.get("image_files") or record.get("image_assets") or []
    return bool(images)


def assess_record(student: Path, record: dict, *, group: str, relative: str) -> dict:
    path = student / relative
    role = str(record.get("role") or record.get("workflow") or "")
    lane = _lane_of(relative, record)
    card = {
        "group": group,
        "id": record.get("id"),
        "scenario_id": record.get("scenario_id"),
        "role": role,
        "level": record.get("level") or record.get("complexity"),
        "technique_id": record.get("technique_id"),
        "technique_fit": record.get("technique_fit"),
        "lane": lane,
        "path": relative,
        "task_sha256": record.get("task_sha256"),
        "in_manifest": bool(record.get("prompt_file")),
    }
    if not path.is_file():
        card.update(disposition="hold_broken", shape="missing", issues=["missing_prompt"], usable_for=[], blocked_claims=_blocked("hold_broken"), contract_excerpt="")
        return card
    text = path.read_text(encoding="utf-8")
    issues = []
    expected = record.get("prompt_sha256")
    actual = sha256_text(text)
    card["prompt_sha256"] = actual
    if expected and actual != expected:
        issues.append("hash_mismatch")
    for attachment in attachment_paths(record):
        if not (student / attachment).is_file():
            issues.append(f"attachment_missing:{attachment}")
    judged = assess_text(
        text,
        role=role,
        group=group,
        technique_fit=record.get("technique_fit"),
        lane=lane,
        needs_vision=_modality(record, relative),
    )
    judged["issues"] = issues + judged["issues"]
    if issues:
        judged["disposition"] = "hold_broken"
        judged["usable_for"] = []
        judged["blocked_claims"] = _blocked("hold_broken")
    card.update(judged)
    return card


def _read_manifest(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def audit_pack(student: Path, manifest_relative: str, group: str) -> list[dict]:
    manifest_path = student / manifest_relative
    pack = manifest_path.parent
    cards = []
    seen: set[str] = set()
    for record in _read_manifest(manifest_path):
        relative = str(record["prompt_file"])
        seen.add(relative)
        cards.append(assess_record(student, record, group=group, relative=relative))
    for relative, record in _extra_lane_files(student, pack, seen):
        cards.append(assess_record(student, record, group=group, relative=relative))
    _apply_parity(cards)
    return cards


def _extra_lane_files(student: Path, pack: Path, seen: set[str]) -> list[tuple[str, dict]]:
    found = []
    for lane in LANE_DIRS:
        root = pack / lane
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            relative = path.relative_to(student).as_posix()
            if relative in seen:
                continue
            role = path.relative_to(root).parts[0]
            found.append((relative, {
                "id": f"extra:{relative}",
                "scenario_id": f"{role}:{path.stem}",
                "role": role,
                "kind": "strategy" if "strategy" in lane else "control",
                "technique_id": None,
                "technique_fit": None,
            }))
    return found


def _apply_parity(cards: list[dict]) -> None:
    by_scenario: dict[str, set[str]] = {}
    for card in cards:
        scenario = card.get("scenario_id")
        digest = card.get("prompt_sha256")
        task = card.get("task_sha256")
        if scenario and task:
            by_scenario.setdefault(str(scenario), set()).add(str(task))
    # task hash is on the manifest record and copied below when present
    broken = {scenario for scenario, digests in by_scenario.items() if len(digests) > 1}
    if not broken:
        return
    for card in cards:
        if card.get("scenario_id") in broken:
            issues = list(card.get("issues") or [])
            issues.append("parity_break")
            card["issues"] = issues
            card["disposition"] = "hold_broken"
            card["usable_for"] = []
            card["blocked_claims"] = _blocked("hold_broken")


def audit_academy(groups_root: Path) -> list[dict]:
    cards: list[dict] = []
    for group, student_rel, manifest_rel in PACKS:
        student = groups_root / student_rel
        manifest = student / manifest_rel
        if not manifest.is_file():
            cards.append({
                "group": group,
                "id": f"missing-manifest:{manifest_rel}",
                "path": manifest_rel,
                "disposition": "hold_broken",
                "issues": ["missing_manifest"],
                "usable_for": [],
                "blocked_claims": _blocked("hold_broken"),
                "shape": "missing",
            })
            continue
        pack_cards = audit_pack(student, manifest_rel, group)
        for card in pack_cards:
            card["task_sha256"] = card.get("task_sha256")
        cards.extend(pack_cards)
    return cards


def stage2_queue(cards: list[dict]) -> list[dict]:
    """One binding question per scenario, preferring a T00 or control row."""
    chosen: dict[str, dict] = {}
    for card in cards:
        if card.get("disposition") != "needs_binding":
            continue
        scenario = str(card.get("scenario_id") or card.get("id"))
        key = f"{card.get('group')}:{scenario}"
        current = chosen.get(key)
        if current is None or _queue_rank(card) < _queue_rank(current):
            chosen[key] = {
                "group": card.get("group"),
                "id": card.get("id"),
                "scenario_id": card.get("scenario_id"),
                "role": card.get("role"),
                "path": card.get("path"),
                "contract_excerpt": card.get("contract_excerpt") or "",
            }
    return [chosen[key] for key in sorted(chosen)]


def _queue_rank(card: dict) -> tuple:
    technique = card.get("technique_id")
    lane = card.get("lane")
    return (0 if technique in {None, "T00"} or lane == "control" else 1, str(card.get("id")))


def summarize(cards: list[dict]) -> dict:
    dispositions: dict[str, int] = {}
    issues: dict[str, int] = {}
    by_group: dict[str, dict[str, int]] = {}
    for card in cards:
        name = str(card.get("disposition"))
        dispositions[name] = dispositions.get(name, 0) + 1
        group = str(card.get("group"))
        bucket = by_group.setdefault(group, {})
        bucket[name] = bucket.get(name, 0) + 1
        for issue in card.get("issues") or []:
            key = str(issue).split(":", 1)[0]
            issues[key] = issues.get(key, 0) + 1
    return {
        "prompts": len(cards),
        "dispositions": dict(sorted(dispositions.items())),
        "issues": dict(sorted(issues.items())),
        "by_group": {key: dict(sorted(value.items())) for key, value in sorted(by_group.items())},
        "stage2_scenarios": len(stage2_queue(cards)),
    }
