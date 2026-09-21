"""Ensure generic rollout framework has no product-specific imports (R7)."""

from __future__ import annotations

import ast
from pathlib import Path

_GENERIC_MODULES = (
    "service_rollout.py",
    "service_source_overlay.py",
    "rollout_registry.py",
)

_BANNED_SUBSTRINGS = (
    "forge_market_studio_rollout",
    "forge_market_source_overlay",
)


def test_generic_modules_avoid_product_imports() -> None:
    root = Path(__file__).resolve().parents[1] / "fleet_server"
    for name in _GENERIC_MODULES:
        path = root / name
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for banned in _BANNED_SUBSTRINGS:
                    assert banned not in node.module, f"{name} imports {node.module}"
        for banned in _BANNED_SUBSTRINGS:
            assert banned not in text, f"{name} references {banned}"
