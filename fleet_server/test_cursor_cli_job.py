"""The cursor CLI job keeps the localhost credential out of the job row."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from fleet_server import cursor_cli_job, store


class CursorCliJobTests(unittest.TestCase):
    def test_credential_is_not_stored(self) -> None:
        secret = "localhost-credential-value"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "cursor-agent"
            binary.write_text("#!/bin/sh\nprintf '%s\\n' \"$CURSOR_API_KEY\"\n", encoding="utf-8")
            binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
            db = root / "fleet.sqlite"
            os.environ["FLEET_CURSOR_AGENT_BIN"] = str(binary)
            try:
                result = cursor_cli_job.submit(
                    db,
                    {"args": ["--print", "hello"], "credential": secret, "timeout_s": 20},
                    inline=True,
                )
            finally:
                os.environ.pop("FLEET_CURSOR_AGENT_BIN", None)
            self.assertEqual(result["http"], 202)
            self.assertNotIn(secret, json.dumps(result))
            conn = store.connect(db)
            try:
                row = store.get_job(conn, result["id"])
            finally:
                conn.close()
            self.assertIsNotNone(row)
            assert row is not None
            blob = json.dumps(row)
            self.assertNotIn(secret, blob)
            self.assertEqual(row["status"], "completed")
            self.assertIn("[redacted]", row["stdout"])
            self.assertEqual(row["argv"], ["--print", "hello"])

    def test_missing_binary_does_not_insert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "fleet.sqlite"
            os.environ["FLEET_CURSOR_AGENT_BIN"] = str(Path(tmp) / "missing-cursor-agent")
            try:
                result = cursor_cli_job.submit(db, {"args": ["--print"], "credential": "localhost-credential-value"})
            finally:
                os.environ.pop("FLEET_CURSOR_AGENT_BIN", None)
            self.assertEqual(result["error"], "cursor_cli_not_configured")
            self.assertFalse(db.exists())

    def test_api_key_flag_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "fleet.sqlite"
            result = cursor_cli_job.submit(
                db,
                {"args": ["--api-key", "other-value"], "credential": "localhost-credential-value"},
            )
            self.assertEqual(result["error"], "credential_in_args")
            self.assertFalse(db.exists())


if __name__ == "__main__":
    unittest.main()
