"""Google session headers for forge-mlx."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

os.environ["FORGE_AUTH_GATE_MODE"] = "mlx"
os.environ["FORGE_AUTH_GATE_SECRET"] = "test-secret"

_GATE = Path(__file__).resolve().parents[1] / "gate.py"
_spec = importlib.util.spec_from_file_location("forge_auth_gate_mlx", _GATE)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["forge_auth_gate_mlx"] = _mod
_spec.loader.exec_module(_mod)


class GateMlxModeTests(unittest.TestCase):
    def test_email_header_without_basic_auth(self) -> None:
        self.assertEqual(_mod.MODE, "mlx")
        headers = _mod.session_upstream_headers({"email": "ada@forgedc.net", "name": "Ada"})
        assert headers is not None
        self.assertEqual(headers.get("X-Forwarded-Email"), "ada@forgedc.net")
        self.assertNotIn("Authorization", headers)


if __name__ == "__main__":
    unittest.main()
