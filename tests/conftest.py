"""Test-only import paths for packages that ship inside deploy/ (not pip-installed with Fleet)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_WEB_BRIDGE = _REPO / "deploy" / "open-webui" / "bridge"
if _WEB_BRIDGE.is_dir() and str(_WEB_BRIDGE) not in sys.path:
    sys.path.insert(0, str(_WEB_BRIDGE))
