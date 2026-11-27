"""Short-lived Open WebUI completion jobs.

The public caller receives an id immediately. This process calls the local
Open WebUI upstream, which can outlast the Cloudflare proxy wait, and stores
only the result.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

JOB_COLLECTION = "/api/forge/completions"
RUNNING_RETRY_AFTER_S = 20
JOB_TTL_S = 9 * 3600
_ID = re.compile(r"[A-Za-z0-9_-]{8,80}")
_lock = threading.Lock()


def job_id_from_path(path: str) -> str | None:
    prefix = JOB_COLLECTION + "/"
    if path.rstrip("/") == JOB_COLLECTION:
        return ""
    if not path.startswith(prefix):
        return None
    job_id = path[len(prefix) :].split("/", 1)[0]
    if not _ID.fullmatch(job_id):
        return None
    return job_id


class CompletionJobs:
    def __init__(
        self,
        directory: Path,
        upstream: str,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        spawn: bool = True,
    ) -> None:
        self.directory = directory
        self.upstream = upstream.rstrip("/")
        self.opener = opener
        self.spawn = spawn
        self.directory.mkdir(parents=True, exist_ok=True)

    def start(self, bearer: str, body: bytes) -> dict[str, Any]:
        job_id = secrets.token_urlsafe(18)
        self._write(job_id, {"id": job_id, "status": "running", "retry_after": RUNNING_RETRY_AFTER_S, "created": time.time()})
        if self.spawn:
            threading.Thread(target=self._run, args=(job_id, bearer, body), name=f"owui-job-{job_id[:8]}", daemon=True).start()
        else:
            self._run(job_id, bearer, body)
        return self.read(job_id) or {"id": job_id, "status": "running", "retry_after": RUNNING_RETRY_AFTER_S}

    def read(self, job_id: str) -> dict[str, Any] | None:
        if not _ID.fullmatch(job_id):
            return None
        path = self._path(job_id)
        if not path.is_file():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        created = float(record.get("created") or 0)
        if created and time.time() - created > JOB_TTL_S:
            path.unlink(missing_ok=True)
            return None
        public = {key: value for key, value in record.items() if key != "created"}
        return public

    def _run(self, job_id: str, bearer: str, body: bytes) -> None:
        request = urllib.request.Request(
            f"{self.upstream}/api/chat/completions",
            data=body,
            headers={
                "Authorization": bearer,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with self.opener(request, timeout=8 * 3600) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            header = exc.headers.get("Retry-After") if exc.headers else None
            if exc.code == 429 or "usage_limit" in detail:
                retry_after = int(header) if header and str(header).isdigit() else 3600
                self._write(
                    job_id,
                    {
                        "id": job_id,
                        "status": "limited",
                        "retry_after": max(60, retry_after),
                        "error": detail,
                        "created": time.time(),
                    },
                )
                return
            self._write(job_id, {"id": job_id, "status": "error", "error": f"HTTP {exc.code}: {detail}", "created": time.time()})
            return
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            self._write(job_id, {"id": job_id, "status": "error", "error": str(exc), "created": time.time()})
            return
        content, model = _completion_text(payload)
        if not content:
            self._write(job_id, {"id": job_id, "status": "error", "error": "Open WebUI returned an empty completion", "created": time.time()})
            return
        self._write(
            job_id,
            {"id": job_id, "status": "done", "model": model, "content": content, "created": time.time()},
        )

    def _path(self, job_id: str) -> Path:
        return self.directory / f"{job_id}.json"

    def _write(self, job_id: str, record: dict[str, Any]) -> None:
        path = self._path(job_id)
        temporary = path.with_suffix(".json.tmp")
        payload = json.dumps(record)
        with _lock:
            temporary.write_text(payload, encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(path)


def _completion_text(payload: dict[str, Any]) -> tuple[str, str]:
    choices = payload.get("choices") or []
    if not choices:
        return "", str(payload.get("model") or "")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        content = "\n".join(str(block.get("text") or "") for block in content if isinstance(block, dict))
    return str(content or "").strip(), str(payload.get("model") or "")
