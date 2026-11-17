"""HTTP client for agentic-dev cursor runs via forge-gateway."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


def _base_url() -> str:
    raw = (
        os.environ.get("FORGE_LLM_BASE_URL")
        or os.environ.get("FORGE_LLM_GATEWAY_URL")
        or ""
    ).strip().rstrip("/")
    if raw.endswith("/v1"):
        return raw
    if raw:
        return f"{raw}/v1"
    return ""


def _bearer() -> str:
    return (
        os.environ.get("FORGE_LLM_GATEWAY_BEARER")
        or os.environ.get("FORGE_LLM_TELEMETRY_BEARER")
        or ""
    ).strip()


def via_gateway_enabled() -> bool:
    return os.environ.get("FORGE_AGENT_VIA_GATEWAY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


@dataclass
class GatewayCursorResult:
    returncode: int
    stdout: str
    stderr: str
    job_id: str | None = None


def _poll_job(base: str, job_id: str, bearer: str, timeout_s: float) -> tuple[int, str, str]:
    deadline = time.time() + timeout_s
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    while time.time() < deadline:
        req = urllib.request.Request(f"{base}/llm/jobs/{job_id}", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        status = str(data.get("status") or "")
        if status == "completed":
            response = data.get("response") if isinstance(data.get("response"), dict) else {}
            text = ""
            choices = response.get("choices") if isinstance(response, dict) else None
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message") if isinstance(choices[0], dict) else {}
                text = str(msg.get("content") or "")
            return 0, text, ""
        if status == "failed":
            return 1, "", str(data.get("error") or "job failed")
        time.sleep(2.0)
    return 124, "", "gateway job poll timed out"


def run_cursor_via_gateway(
    *,
    model: str,
    workspace: str,
    prompt: str,
    timeout_s: int,
    async_job: bool | None = None,
) -> GatewayCursorResult:
    base = _base_url()
    bearer = _bearer()
    if not base:
        return GatewayCursorResult(127, "", "FORGE_LLM_BASE_URL not set")
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "forge_cursor": {
            "mode": "agent",
            "force": True,
            "workspace": workspace,
            "output_format": "text",
            "timeout_s": float(timeout_s),
        },
    }
    use_async = async_job
    if use_async is None:
        use_async = timeout_s > int(os.environ.get("FORGE_LLM_CLI_ASYNC_TIMEOUT_S", "180"))
    headers = {
        "Content-Type": "application/json",
        "X-Forge-Consumer": "agentic-dev",
    }
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if use_async:
        headers["X-Forge-Async"] = "1"
        headers["X-Forge-Webhook-Url"] = os.environ.get(
            "FORGE_AGENT_WEBHOOK_URL", "https://localhost/noop"
        )
        headers["X-Forge-Webhook-Secret"] = os.environ.get(
            "FORGE_AGENT_WEBHOOK_SECRET", "noop"
        )
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=min(60, timeout_s)) as resp:
            raw = resp.read().decode()
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
        raw = exc.read().decode(errors="replace")
        return GatewayCursorResult(1, "", raw)
    except urllib.error.URLError as exc:
        return GatewayCursorResult(127, "", str(exc.reason))
    if code == 202:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return GatewayCursorResult(1, "", raw)
        job_id = str(data.get("job_id") or "")
        rc, out, err = _poll_job(base, job_id, bearer, float(timeout_s))
        return GatewayCursorResult(rc, out, err, job_id=job_id or None)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return GatewayCursorResult(0 if code == 200 else 1, raw, "")
    if code >= 400:
        return GatewayCursorResult(1, "", raw)
    choices = data.get("choices") if isinstance(data, dict) else None
    text = ""
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") if isinstance(choices[0], dict) else {}
        text = str(msg.get("content") or "")
    return GatewayCursorResult(0, text, "")