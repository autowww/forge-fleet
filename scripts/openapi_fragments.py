#!/usr/bin/env python3
"""Load, write, and bundle OpenAPI from docs/schemas/openapi/ fragments."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FRAG_DIR = REPO / "docs" / "schemas" / "openapi"
BUNDLE_PATH = REPO / "docs" / "schemas" / "openapi.json"


def fragments_available() -> bool:
    return (FRAG_DIR / "openapi-root.json").is_file()


def path_group(path_key: str) -> str:
    parts = path_key.strip("/").split("/")
    group = parts[1] if len(parts) >= 2 and parts[0] == "v1" else (parts[0] if parts else "root")
    return re.sub(r"[^a-z0-9_-]+", "-", group.lower())


def load_openapi_doc() -> dict:
    """Assemble OpenAPI from fragments, or read the legacy monolith if present."""
    root_path = FRAG_DIR / "openapi-root.json"
    if root_path.is_file():
        doc = json.loads(root_path.read_text(encoding="utf-8"))
        paths: dict = {}
        paths_dir = FRAG_DIR / "paths"
        if paths_dir.is_dir():
            for p in sorted(paths_dir.glob("*.json")):
                paths.update(json.loads(p.read_text(encoding="utf-8")))
        doc["paths"] = paths
        comp = FRAG_DIR / "components.json"
        if comp.is_file():
            doc["components"] = json.loads(comp.read_text(encoding="utf-8"))
        return doc
    if BUNDLE_PATH.is_file():
        return json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        "OpenAPI missing: add docs/schemas/openapi/openapi-root.json or docs/schemas/openapi.json"
    )


def write_openapi_fragments(doc: dict) -> None:
    """Persist a full OpenAPI document into fragment files under docs/schemas/openapi/."""
    work = json.loads(json.dumps(doc))
    paths = work.pop("paths", {})
    components = work.pop("components", None)

    FRAG_DIR.mkdir(parents=True, exist_ok=True)
    (FRAG_DIR / "openapi-root.json").write_text(
        json.dumps(work, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if components is not None:
        (FRAG_DIR / "components.json").write_text(
            json.dumps(components, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    paths_dir = FRAG_DIR / "paths"
    paths_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, dict] = {}
    for path_key, item in paths.items():
        groups.setdefault(path_group(path_key), {})[path_key] = item

    keep = {f"{name}.json" for name in groups}
    for stale in paths_dir.glob("*.json"):
        if stale.name not in keep:
            stale.unlink()

    for group, items in sorted(groups.items()):
        (paths_dir / f"{group}.json").write_text(
            json.dumps(items, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def bundle_openapi() -> None:
    """Write docs/schemas/openapi.json from fragments (for Hosting /schemas/ and CI)."""
    doc = load_openapi_doc()
    BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
