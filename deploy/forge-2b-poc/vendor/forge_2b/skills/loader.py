"""Load a skill directory (YAML manifest + JSON Schema + system prompt)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SkillBundle:
    skill_id: str
    version: str
    skill_dir: Path
    decision_schema: dict[str, Any]
    system_prompt: str
    categories: tuple[str, ...]
    output_contract: str
    legacy_reduce: bool
    taxonomy: dict[str, Any]
    reduce: dict[str, Any]


def default_skill_dir() -> Path:
    """Directory of the bundled 10-K skill.

    Layouts:
    - Dev repo: ``forge-2b-poc/src/forge_2b/skills/loader.py`` → ``forge-2b-poc/skills/sec-10k-impact``.
    - Docker (``PYTHONPATH=/app``): ``/app/forge_2b/skills/loader.py`` → ``/app/skills/sec-10k-impact``.
    """
    override = os.environ.get("FORGE_2B_SKILL_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    here = Path(__file__).resolve()
    for rel in (3, 2):  # repo root, then image root
        cand = here.parents[rel] / "skills" / "sec-10k-impact"
        if cand.is_dir():
            return cand
    return here.parents[3] / "skills" / "sec-10k-impact"


def load_skill_bundle(skill_dir: Path | None = None) -> SkillBundle:
    skill_dir = (skill_dir or default_skill_dir()).resolve()
    manifest_path = skill_dir / "skill.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"skill manifest must be a mapping: {manifest_path}")

    schema_path = skill_dir / str(raw.get("decision_schema") or "decision.schema.json")
    prompt_path = skill_dir / str(raw.get("system_prompt") or "prompt.system.md")
    schema_obj = json.loads(schema_path.read_text(encoding="utf-8"))
    system_prompt = prompt_path.read_text(encoding="utf-8").strip()
    if system_prompt.endswith("\n"):
        system_prompt = system_prompt.rstrip("\n")

    cats = _categories_from_schema(schema_obj)
    legacy = raw.get("legacy_reduce")
    if legacy is None:
        legacy = False
    tax_path = skill_dir / str(raw.get("taxonomy") or "taxonomy.yaml")
    taxonomy = yaml.safe_load(tax_path.read_text(encoding="utf-8"))
    if not isinstance(taxonomy, dict):
        raise ValueError(f"taxonomy must be a mapping: {tax_path}")
    reduce_cfg = raw.get("reduce") or {}
    if not isinstance(reduce_cfg, dict):
        raise ValueError("skill manifest 'reduce' must be a mapping when present")
    return SkillBundle(
        skill_id=str(raw.get("skill_id") or "unknown"),
        version=str(raw.get("version") or "0"),
        skill_dir=skill_dir,
        decision_schema=schema_obj,
        system_prompt=system_prompt,
        categories=cats,
        output_contract=str(raw.get("output_contract") or ""),
        legacy_reduce=bool(legacy),
        taxonomy=taxonomy,
        reduce=dict(reduce_cfg),
    )


def _categories_from_schema(schema_obj: dict[str, Any]) -> tuple[str, ...]:
    try:
        enum = schema_obj["properties"]["statements"]["items"]["properties"]["category"]["enum"]
    except (KeyError, TypeError) as ex:
        raise ValueError("decision schema missing statements[].category.enum") from ex
    if not enum:
        raise ValueError("category enum is empty")
    return tuple(str(x) for x in enum)
