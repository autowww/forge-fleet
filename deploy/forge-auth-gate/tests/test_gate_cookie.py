"""Cookie signing for forge-auth-gate."""

from __future__ import annotations

import importlib.util
import sys
import time
import unittest
from pathlib import Path

_GATE = Path(__file__).resolve().parents[1] / "gate.py"
_spec = importlib.util.spec_from_file_location("forge_auth_gate", _GATE)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["forge_auth_gate"] = _mod
_spec.loader.exec_module(_mod)


class GateCookieTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        exp = time.time() + 60
        raw = _mod._sign_cookie("alice@example.com", "Alice", exp)
        hit = _mod._read_cookie(raw)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["email"], "alice@example.com")

    def test_tamper(self) -> None:
        exp = time.time() + 60
        raw = _mod._sign_cookie("a@b.co", "A", exp)
        bad = raw[:-2] + "xx"
        self.assertIsNone(_mod._read_cookie(bad))


if __name__ == "__main__":
    unittest.main()