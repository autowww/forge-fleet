"""Fail-open agent_run posts to forge-gateway telemetry (no task outcome side effects)."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

_USAGE_RE = re.compile(
    r'"usage"\s*:\s*\{[^}]*"prompt_tokens"\s*:\s*(\d+)[^}]*"completion_tokens"\s*:\s*(\d+)',
    re.DOTALL,
)


def _telemetry_url() -> str:
    raw = str(os.environ.get("FORGE_LLM_TELEMETRY_URL") or "").strip()
    if not raw:
        return ""
    if raw.endswith("/v1/llm/telemetry/events"):
        return raw
    return raw.rstrip("/") + "/v1/llm/telemetry/events"


def _telemetry_bearer() -> str:
    for key in (
        "FORGE_LLM_TELEMETRY_BEARER",
        "FORGE_LLM_GATEWAY_BEARER",
        "LLM_BEARER_TOKEN",
        "FORGE_API_TOKEN",
    ):
        val = str(os.environ.get(key) or "").strip()
        if val:
            return val
    return ""


def redact_secrets(text: str, secrets: list[str]) -> str:
    out = text
    for s in secrets:
        if s:
            out = out.replace(s, "[redacted]")
    return out


def try_parse_usage(stdout: str) -> tuple[int, int] | None:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            usage = data.get("usage")
            if isinstance(usage, dict):
                tin = int(usage.get("prompt_tokens") or 0)
                tout = int(usage.get("completion_tokens") or 0)
                if tin or tout:
                    return tin, tout
    except json.JSONDecodeError:
        pass
    m = _USAGE_RE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def build_agent_run_event(
    *,
    consumer: str,
    trace_id: str,
    model: str,
    duration_ms: int,
    exit_code: int,
    llm: bool,
    stdout: str = "",
) -> dict[str, Any]:
    secrets = [s for s in (os.environ.get("CURSOR_API_KEY"), os.environ.get("GIT_TOKEN")) if s]
    safe_out = redact_secrets(stdout[-8000:], secrets)
    metrics: dict[str, Any] = {
        "model": model,
        "duration_ms": int(duration_ms),
        "exit_code": int(exit_code),
        "llm": bool(llm),
        "token_quality": "unavailable",
    }
    usage = try_parse_usage(stdout)
    if usage:
        tin, tout = usage
        metrics["token_quality"] = "measured"
        metrics["prompt_tokens"] = tin
        metrics["completion_tokens"] = tout
    if safe_out and metrics["token_quality"] == "unavailable":
        metrics["stdout_preview"] = safe_out[-500:]
    return {
        "kind": "agent_run",
        "source": "client",
        "consumer": consumer,
        "trace_id": trace_id,
        "metrics": metrics,
    }


def post_agent_run_event(event: dict[str, Any], *, recorder_note: Any | None = None) -> bool:
    url = _telemetry_url()
    bearer = _telemetry_bearer()
    if not url or not bearer:
        return False
    body = json.dumps(event).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Forge-Consumer": str(event.get("consumer") or "agentic-dev"),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            _ = resp.read()
        return True
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        if recorder_note is not None:
            try:
                recorder_note("agent_telemetry", error=type(exc).__name__)
            except Exception:  # noqa: BLE001
                pass
        return False


def cursor_step_duration_ms(steps: list[dict[str, Any]]) -> int:
    for row in reversed(steps):
        if row.get("step") == "cursor" and row.get("duration_s") is not None:
            return int(float(row["duration_s"]) * 1000)
    return 0


def report_agent_run_from_cursor(
    *,
    recorder: Any,
    task_id: str,
    model: str,
    proc: Any,
    consumer: str = "agentic-dev",
) -> None:
    duration_ms = cursor_step_duration_ms(recorder.steps)
    event = build_agent_run_event(
        consumer=consumer,
        trace_id=task_id,
        model=model,
        duration_ms=duration_ms,
        exit_code=int(proc.returncode),
        llm=True,
        stdout=(proc.stdout or "") + "\n" + (proc.stderr or ""),
    )
    post_agent_run_event(event, recorder_note=recorder.note)


def report_code_review_marker(*, recorder: Any, task_id: str) -> None:
    duration_ms = 0
    for row in reversed(recorder.steps):
        if row.get("duration_s") is not None:
            duration_ms += int(float(row["duration_s"]) * 1000)
    event = build_agent_run_event(
        consumer="code-review",
        trace_id=task_id,
        model="",
        duration_ms=duration_ms,
        exit_code=0,
        llm=False,
        stdout="",
    )
    post_agent_run_event(event, recorder_note=recorder.note)