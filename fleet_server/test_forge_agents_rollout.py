import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fleet_server import forge_agents_rollout as far


class RolloutTests(unittest.TestCase):
    def test_git_sync_argv_clone_vs_fetch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "forge-agents"
            cmds = far.git_sync_argv(root, "main")
            self.assertEqual(cmds[0][:3], ["git", "clone", "--branch"])
            self.assertIn(far.REPO_URL, cmds[0])
            (root / ".git").mkdir(parents=True)
            cmds = far.git_sync_argv(root, "main")
            self.assertEqual([c[3] for c in cmds], ["fetch", "checkout", "reset"])
            self.assertIn("origin/main", cmds[-1])
            self.assertTrue(all("--force" not in c and "push" not in c for c in cmds))

    def test_schedule_rejects_bad_ref(self):
        with tempfile.TemporaryDirectory() as td:
            out = far.schedule(Path(td), {"ref": "main; rm -rf /"})
            self.assertEqual(out["error"], "invalid_ref")
            out = far.schedule(Path(td), {"ref": "--upload-pack=x"})
            self.assertEqual(out["error"], "invalid_ref")

    def test_sync_rollout_stops_when_env_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "fa"
            (root / ".git").mkdir(parents=True)
            with mock.patch.dict(os.environ, {"FLEET_FORGE_AGENTS_ROOT": str(root)}), \
                    mock.patch.object(far, "_run", return_value=0), \
                    mock.patch.object(far, "_head_sha", return_value="abc123abc123"):
                out = far.schedule(Path(td) / "data", {"ref": "main"}, sync=True)
            self.assertEqual(out["error"], "env_roadrunner_missing")
            self.assertEqual(out["git_sha"], "abc123abc123")
            self.assertFalse(far._STATE["running"])

    def test_status_reads_log_tail(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            far.log_path(data).write_text("hello\n")
            st = far.status(data)
            self.assertTrue(st["ok"]) and self.assertIn("hello", st["log_tail"])


if __name__ == "__main__":
    unittest.main()
