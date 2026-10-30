"""Temp jobs return JSON summaries and refuse filing HTML."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from fleet_server import temp_jobs


class TempJobTests(unittest.TestCase):
    def test_probe_result_is_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "fleet.sqlite"
            queued = temp_jobs.submit(db, {"recipe": "probe", "args": {"filing": "absent"}}, inline=True)
            self.assertEqual(queued["http"], 202)
            body = temp_jobs.result(db, queued["id"])
            self.assertEqual(body["http"], 200)
            self.assertEqual(body["result"]["recipe"], "probe")
            self.assertNotIn("original.html", json.dumps(body))

    def test_html_payload_is_not_stored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "python"
            binary.write_text(
                "#!/bin/sh\nprintf '%s\\n' '<ix:nonFraction name=\"us-gaap:Revenues\">1</ix:nonFraction>'\n",
                encoding="utf-8",
            )
            binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
            db = root / "fleet.sqlite"
            os.environ["FLEET_TEMP_JOB_PYTHON"] = str(binary)
            try:
                queued = temp_jobs.submit(
                    db,
                    {"recipe": "python_module", "module": "forge_market.analysis.sec_fic.financial_facts.remote", "timeout_s": 20},
                    inline=True,
                )
            finally:
                os.environ.pop("FLEET_TEMP_JOB_PYTHON", None)
            body = temp_jobs.result(db, queued["id"])
            self.assertEqual(body["http"], 409)
            self.assertNotIn("us-gaap:Revenues", json.dumps(body))

    def test_market_container_command_is_exec_not_shell(self) -> None:
        os.environ["FLEET_TEMP_JOB_CONTAINER"] = "forge-market-app"
        os.environ.pop("FLEET_TEMP_JOB_PYTHON", None)
        try:
            argv = temp_jobs.module_command("forge_market.analysis.sec_fic.financial_facts.remote")
        finally:
            os.environ.pop("FLEET_TEMP_JOB_CONTAINER", None)
        self.assertEqual(argv[:4], ["docker", "exec", "-i", "-e"])
        self.assertIn("forge-market-app", argv)
        self.assertNotIn("bash", argv)
        self.assertNotIn("sh", argv)

    def test_unknown_container_is_not_used(self) -> None:
        os.environ["FLEET_TEMP_JOB_CONTAINER"] = "other-container"
        os.environ["FLEET_TEMP_JOB_PYTHON"] = ""
        try:
            argv = temp_jobs.module_command("forge_market.analysis.sec_fic.financial_facts.remote")
        finally:
            os.environ.pop("FLEET_TEMP_JOB_CONTAINER", None)
            os.environ.pop("FLEET_TEMP_JOB_PYTHON", None)
        self.assertNotIn("other-container", argv)
        self.assertNotIn("docker", argv)

    def test_unknown_module_is_rejected_before_insert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "fleet.sqlite"
            queued = temp_jobs.submit(db, {"recipe": "python_module", "module": "os"})
            self.assertEqual(queued["error"], "module_not_allowed")
            self.assertFalse(db.exists())


if __name__ == "__main__":
    unittest.main()
