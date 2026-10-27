import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fleet_server import branch_gc_job


def _fake_fetch(now):
    old = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    deleted = []

    def fetch(method, path, token, body=None):
        if method == "GET" and path.endswith("/branches?per_page=100"):
            return 200, [
                {"name": "main", "commit": {"sha": "m"}},
                {"name": "agent/roadrunner/req_task_0000aaaa-old", "commit": {"sha": "o"}},
                {"name": "agent/roadrunner/req_task_0000bbbb-fresh", "commit": {"sha": "f"}},
                {"name": "agent/roadrunner/req_task_0000cccc-pr", "commit": {"sha": "p"}},
            ]
        if method == "GET" and "/pulls?" in path:
            return 200, [{"head": {"ref": "agent/roadrunner/req_task_0000cccc-pr"}}]
        if method == "GET" and "/commits/" in path:
            sha = path.rsplit("/", 1)[1]
            when = fresh if sha == "f" else old
            return 200, {"commit": {"committer": {"date": when}}}
        if method == "DELETE":
            deleted.append(path)
            return 204, None
        return 404, None

    return fetch, deleted


class BranchGcTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"FLEET_AGENTIC_GIT_TOKEN": "github_pat_test", "FLEET_AGENTIC_REPO_ALLOWLIST": "autowww/*"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.now = datetime.now(timezone.utc)

    def test_dry_run_lists_only_expired_without_open_pr(self):
        fetch, deleted = _fake_fetch(self.now)
        out = branch_gc_job.run({"dry_run": True, "repos": ["autowww/forge-calc-canary"]}, fetch=fetch)
        self.assertTrue(out["ok"])
        self.assertEqual([c["branch"] for c in out["candidates"]], ["agent/roadrunner/req_task_0000aaaa-old"])
        self.assertEqual(deleted, [])

    def test_apply_deletes_candidates(self):
        fetch, deleted = _fake_fetch(self.now)
        out = branch_gc_job.run({"dry_run": False, "repos": ["autowww/forge-calc-canary"]}, fetch=fetch)
        self.assertEqual(len(out["deleted"]), 1)
        self.assertTrue(out["deleted"][0]["deleted"])
        self.assertIn("agent/roadrunner/req_task_0000aaaa-old", deleted[0])

    def test_rejects_repo_outside_allowlist(self):
        fetch, _ = _fake_fetch(self.now)
        out = branch_gc_job.run({"repos": ["evil/repo"]}, fetch=fetch)
        self.assertEqual(out["error"], "no_repos")

    def test_requires_git_token(self):
        with mock.patch.dict(os.environ, {"FLEET_AGENTIC_GIT_TOKEN": ""}):
            out = branch_gc_job.run({"repos": ["autowww/x"]})
        self.assertEqual(out["error"], "git_token_not_configured")


if __name__ == "__main__":
    unittest.main()
