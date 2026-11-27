"""Mercury completion jobs store the result and not the caller bearer."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from email.message import Message
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "forge-auth-gate"))

from completion_jobs import CompletionJobs, job_id_from_path


class _Body:
    def __init__(self, payload: dict) -> None:
        self.raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self.raw

    def __enter__(self) -> "_Body":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def test_job_id_path() -> None:
    assert job_id_from_path("/api/forge/completions") == ""
    assert job_id_from_path("/api/forge/completions/abcdefgh") == "abcdefgh"
    assert job_id_from_path("/api/forge/completions/no") is None


def test_finished_job_omits_the_bearer(tmp_path: Path) -> None:
    def opener(request, timeout):
        assert timeout == 8 * 3600
        return _Body({"model": "gemini-thinking", "choices": [{"message": {"content": "pong"}}]})

    jobs = CompletionJobs(tmp_path, "http://127.0.0.1:19808", opener=opener, spawn=False)
    record = jobs.start("Bearer secret-token", b"{}")
    assert record["status"] == "done"
    assert record["content"] == "pong"
    assert record["model"] == "gemini-thinking"
    saved = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert "secret-token" not in saved


def test_limit_is_a_finished_job(tmp_path: Path) -> None:
    headers = Message()
    headers["Retry-After"] = "120"

    def opener(request, timeout):
        raise urllib.error.HTTPError(
            "http://upstream",
            429,
            "limit",
            headers,
            io.BytesIO(b"usage_limit retry_after=120"),
        )

    jobs = CompletionJobs(tmp_path, "http://127.0.0.1:19808", opener=opener, spawn=False)
    record = jobs.start("Bearer secret-token", b"{}")
    assert record["status"] == "limited"
    assert record["retry_after"] == 120
    assert "secret-token" not in next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
