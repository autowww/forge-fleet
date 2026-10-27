"""Agentic dev rail: envelope validation, courier state machine, redaction, run_task guards."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fleet_server import agentic_dev_job as adj
from fleet_server import store

_SECRET = "crsr_unit_test_secret_value_000000"
_TOKEN = "github_pat_unit_test_token_000000000000"


def _envelope(**over: object) -> dict:
    body = {
        "task_id": "req_task_0a1b2c3d",
        "repo": "autowww/forge-workcells",
        "base_ref": "master",
        "branch": "agent/roadrunner/req_task_0a1b2c3d-readme-agent-lane",
        "goal": "Add a one-line Agent lane note under README Related.",
        "verify": ["python3 -m pytest -q"],
        "allow_paths": ["README.md", "docs/**"],
        "model": "composer-2.5",
        "timeout_s": 600,
    }
    body.update(over)
    return body


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.db = self.data_dir / "fleet.sqlite"
        self.env = mock.patch.dict(os.environ, {
            "FLEET_AGENTIC_GIT_TOKEN": _TOKEN,
            "FLEET_AGENTIC_DEV_RUNNER": "host",
            "FLEET_CURSOR_AGENT_BIN": "/bin/true",
        })
        self.env.start()
        # Never run the real pipeline in unit tests.
        self.runner = mock.patch.object(adj, "_run_host", return_value=(0, ""))
        self.runner.start()

    def tearDown(self) -> None:
        self.runner.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _job(self, job_id: str) -> dict:
        conn = store.connect(self.db)
        try:
            return store.get_job(conn, job_id) or {}
        finally:
            conn.close()


class ValidationTests(_Base):
    def test_rejects_filesystem_path_repo(self) -> None:
        out = adj.submit(self.db, self.data_dir, _envelope(repo="/home/lzvyahin/Code/forge-agents", credential=_SECRET))
        self.assertEqual(out["error"], "invalid_repo")

    def test_rejects_repo_outside_allowlist(self) -> None:
        out = adj.submit(self.db, self.data_dir, _envelope(repo="someone/else", credential=_SECRET))
        self.assertEqual(out["error"], "repo_not_allowed")

    def test_rejects_branch_outside_agent_lane(self) -> None:
        out = adj.submit(self.db, self.data_dir, _envelope(branch="feature/x", credential=_SECRET))
        self.assertEqual(out["error"], "invalid_branch")

    def test_rejects_branch_task_mismatch(self) -> None:
        out = adj.submit(self.db, self.data_dir, _envelope(branch="agent/roadrunner/req_task_ffffffff-other", credential=_SECRET))
        self.assertEqual(out["error"], "branch_task_mismatch")

    def test_rejects_secret_in_goal(self) -> None:
        out = adj.submit(self.db, self.data_dir, _envelope(goal=f"use {_SECRET}", credential=_SECRET))
        self.assertEqual(out["error"], "credential_in_request")

    def test_requires_git_token(self) -> None:
        with mock.patch.dict(os.environ, {"FLEET_AGENTIC_GIT_TOKEN": ""}):
            out = adj.submit(self.db, self.data_dir, _envelope(credential=_SECRET))
        self.assertEqual(out["error"], "git_token_not_configured")

    def test_digest_is_stable_and_excludes_node(self) -> None:
        env_a, _ = adj.validate_envelope(_envelope(node="local"))
        env_b, _ = adj.validate_envelope(_envelope(node="auto"))
        assert env_a and env_b
        self.assertEqual(adj.canonical_digest(env_a), adj.canonical_digest(env_b))
        self.assertEqual(len(adj.canonical_digest(env_a)), 64)

    def test_approval_digest_mismatch_is_409(self) -> None:
        out = adj.submit(self.db, self.data_dir, _envelope(credential=_SECRET, approval={"digest": "0" * 64}))
        self.assertEqual(out["http"], 409)
        self.assertEqual(out["error"], "approval_digest_mismatch")


class CourierTests(_Base):
    def test_waiting_until_credential_attached_then_runs(self) -> None:
        out = adj.submit(self.db, self.data_dir, _envelope(credential_ref="courier"))
        self.assertEqual(out["status"], adj.STATUS_WAITING)
        job = self._job(out["id"])
        self.assertEqual(job["status"], adj.STATUS_WAITING)
        self.assertFalse(job["meta"]["credential_attached"])
        self.assertNotIn(_SECRET, json.dumps(job, default=str))

        pending = adj.list_pending_credentials(self.db)
        self.assertEqual([p["id"] for p in pending["pending"]], [out["id"]])
        self.assertEqual(pending["pending"][0]["digest"], out["digest"])
        self.assertNotIn("goal", pending["pending"][0])

        attached = adj.attach_credential(self.db, self.data_dir, out["id"], {"credential": _SECRET}, inline=True)
        self.assertEqual(attached["http"], 202)
        job = self._job(out["id"])
        self.assertTrue(job["meta"]["credential_attached"])
        self.assertNotIn(_SECRET, json.dumps(job, default=str))
        self.assertNotIn(_TOKEN, json.dumps(job, default=str))
        self.assertIn(job["status"], ("failed", "held", "completed"))

    def test_second_attach_is_rejected(self) -> None:
        out = adj.submit(self.db, self.data_dir, _envelope(credential_ref="courier"))
        adj.attach_credential(self.db, self.data_dir, out["id"], {"credential": _SECRET}, inline=True)
        again = adj.attach_credential(self.db, self.data_dir, out["id"], {"credential": _SECRET}, inline=True)
        self.assertEqual(again["http"], 409)

    def test_inline_submit_runs_and_stores_redacted_result(self) -> None:
        def fake_run(task_dir: Path, out_dir: Path, envelope: dict, secret: str, token: str) -> tuple[int, str]:
            (out_dir / "result.json").write_text(json.dumps({
                "status": "pushed", "head_sha": "a" * 40, "base_sha": "b" * 40,
                "pr_url": "https://github.com/autowww/forge-workcells/pull/1",
                "note": f"token {token} secret {secret}",
            }), encoding="utf-8")
            return 0, f"stderr with {secret}"

        self.runner.stop()
        with mock.patch.object(adj, "_run_host", side_effect=fake_run):
            out = adj.submit(self.db, self.data_dir, _envelope(credential=_SECRET), inline=True)
        self.runner.start()
        job = self._job(out["id"])
        self.assertEqual(job["status"], "completed")
        blob = json.dumps(job, default=str)
        self.assertNotIn(_SECRET, blob)
        self.assertNotIn(_TOKEN, blob)
        self.assertEqual(job["worker_result"]["head_sha"], "a" * 40)

    def test_get_view(self) -> None:
        out = adj.submit(self.db, self.data_dir, _envelope(credential_ref="courier"))
        view = adj.get(self.db, out["id"])
        self.assertEqual(view["http"], 200)
        self.assertEqual(view["envelope"]["repo"], "autowww/forge-workcells")
        self.assertEqual(view["status"], adj.STATUS_WAITING)


class PeerTests(_Base):
    def test_unknown_peer_is_409(self) -> None:
        out = adj.submit(self.db, self.data_dir, _envelope(credential=_SECRET, node="nowhere"))
        self.assertEqual(out["http"], 409)
        self.assertEqual(out["error"], "peer_unavailable")

    def test_auto_prefers_local_when_free(self) -> None:
        self.assertEqual(adj.choose_node(self.db, self.data_dir), "local")

    def test_auto_forwards_when_local_full(self) -> None:
        with mock.patch.dict(os.environ, {"FLEET_AGENTIC_DEV_MAX_RUNNING": "0"}), \
             mock.patch.object(adj.remote_peers, "list_peers", return_value={"peers": [{"id": "node-b"}]}), \
             mock.patch.object(adj, "peer_capacity", return_value={"http": 200, "agentic_dev": True, "free": 1}):
            self.assertEqual(adj.choose_node(self.db, self.data_dir), "node-b")


def _load_run_task():
    path = adj.deploy_dir() / "run_task.py"
    spec = importlib.util.spec_from_file_location("run_task", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class RunTaskGuardTests(unittest.TestCase):
    def test_path_guard(self) -> None:
        rt = _load_run_task()
        bad = rt.path_guard(["README.md", ".github/workflows/ci.yml", "src/x.py"], ["README.md", "docs/**"], [".github/**"])
        self.assertEqual(bad, [".github/workflows/ci.yml", "src/x.py"])
        self.assertEqual(rt.path_guard(["a/b.py"], ["**"], []), [])

    def test_branch_and_repo_regex(self) -> None:
        rt = _load_run_task()
        self.assertTrue(rt.BRANCH_RE.match("agent/reviewer/req_task_0a1b2c3d-fix-x"))
        self.assertFalse(rt.BRANCH_RE.match("main"))
        self.assertFalse(rt.REPO_RE.match("/tmp/x"))

    def test_secret_scan_flags_key_material(self) -> None:
        rt = _load_run_task()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "ok.txt").write_text("hello", encoding="utf-8")
            (root / "bad.txt").write_text("key = crsr_abcdefghijklmnop", encoding="utf-8")
            self.assertEqual(rt.secret_scan(root, ["ok.txt", "bad.txt"]), ["bad.txt"])


if __name__ == "__main__":
    unittest.main()
