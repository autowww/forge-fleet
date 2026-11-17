"""Composer and Grok completions through the Cursor CLI.

``composer*`` and ``grok*`` never go to Ollama. When
``FORGE_LLM_CLI_UPSTREAM_URL`` is set, the gateway forwards the OpenAI body
there (the laptop CLI bridge). Otherwise it runs ``cursor-agent`` on this host.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from fastapi.responses import Response

from control_plane.config import DEFAULT_HOLD_TIMEOUT_SEC
from control_plane.context import ForgeContext
from control_plane.request_telemetry import record_cli_completion

_PREFIX = "forge-llm."
DEFAULT_CLI_CWD = "/tmp/forge-llm-cli"
CLI_ASYNC_TIMEOUT_DEFAULT = 180.0


def normalize_model(model: str) -> str:
    name = (model or "").strip()
    if name.startswith(_PREFIX):
        name = name[len(_PREFIX) :]
    return name


def is_cli_model(model: str) -> bool:
    name = normalize_model(model).lower()
    if name == "composer" or name.startswith("composer-"):
        return True
    if name == "grok" or name.startswith("grok-"):
        return True
    from control_plane.cli_catalog import is_catalog_cli_model

    return is_catalog_cli_model(model)


def cli_model_id(model: str) -> str:
    from control_plane.cli_catalog import resolve_cursor_model_id

    return resolve_cursor_model_id(model)


def default_cli_cwd() -> Path:
    return Path(os.environ.get("FORGE_LLM_CLI_CWD", DEFAULT_CLI_CWD))


def workspace_roots() -> list[Path]:
    raw = (os.environ.get("FORGE_LLM_CLI_WORKSPACE_ROOTS") or "").strip()
    if raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return [Path(p).resolve() for p in parts]
    return [default_cli_cwd().resolve()]


def parse_forge_cursor(body: dict[str, Any] | None) -> dict[str, Any]:
    base = default_cli_cwd()
    out: dict[str, Any] = {
        "mode": "ask",
        "force": False,
        "output_format": "text",
        "workspace": str(base),
        "timeout_s": None,
    }
    if not isinstance(body, dict):
        return out
    raw = body.get("forge_cursor")
    if not isinstance(raw, dict):
        if body.get("timeout") is not None:
            try:
                out["timeout_s"] = float(body.get("timeout"))
            except (TypeError, ValueError):
                pass
        return out
    mode = str(raw.get("mode") or "ask").strip().lower()
    if mode in ("ask", "agent", "plan"):
        out["mode"] = mode
    if raw.get("force") is True:
        out["force"] = True
    fmt = str(raw.get("output_format") or "text").strip().lower()
    if fmt in ("text", "json"):
        out["output_format"] = fmt
    ws = raw.get("workspace")
    if isinstance(ws, str) and ws.strip():
        out["workspace"] = ws.strip()
    if raw.get("timeout_s") is not None:
        try:
            out["timeout_s"] = float(raw["timeout_s"])
        except (TypeError, ValueError):
            pass
    elif body.get("timeout") is not None:
        try:
            out["timeout_s"] = float(body.get("timeout"))
        except (TypeError, ValueError):
            pass
    return out


def validate_workspace(path_str: str) -> tuple[Path | None, str | None]:
    try:
        target = Path(path_str).expanduser().resolve()
    except (OSError, RuntimeError):
        return None, "invalid workspace path"
    for root in workspace_roots():
        try:
            target.relative_to(root)
            return target, None
        except ValueError:
            continue
    return None, "workspace not under FORGE_LLM_CLI_WORKSPACE_ROOTS"


def cli_async_threshold() -> float:
    raw = (os.environ.get("FORGE_LLM_CLI_ASYNC_TIMEOUT_S") or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return CLI_ASYNC_TIMEOUT_DEFAULT


def cli_requires_async(body: dict[str, Any]) -> bool:
    fc = parse_forge_cursor(body)
    if fc.get("mode") == "agent":
        return True
    timeout = fc.get("timeout_s")
    if timeout is None:
        try:
            timeout = float(body.get("timeout")) if body.get("timeout") is not None else None
        except (TypeError, ValueError):
            timeout = None
    if timeout is not None and float(timeout) > cli_async_threshold():
        return True
    return False


def render_prompt(messages: list[Any], *, mode: str) -> str:
    parts: list[str] = []
    if mode == "ask":
        parts.append(
            "Reply with only the assistant message. Do not use tools. Do not edit files."
        )
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = message.get("content")
        if isinstance(content, list):
            content = "\n".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        text = content if isinstance(content, str) else ""
        if text.strip():
            parts.append(f"{role}:\n{text}")
    if not parts:
        return ""
    if mode != "ask" and len(parts) == 1:
        return parts[0].split(":\n", 1)[-1] if ":\n" in parts[0] else parts[0]
    return "\n\n".join(parts)


def build_cursor_argv(
    *,
    binary: str,
    model: str,
    workspace: Path,
    prompt: str,
    forge_cursor: dict[str, Any],
) -> list[str]:
    mode = str(forge_cursor.get("mode") or "ask")
    force = bool(forge_cursor.get("force"))
    output_format = str(forge_cursor.get("output_format") or "text")
    cmd = [
        binary,
        "--print",
        "--trust",
        "--model",
        cli_model_id(model),
        "--output-format",
        output_format,
        "--workspace",
        str(workspace),
    ]
    if mode in ("ask", "plan"):
        cmd.extend(["--mode", mode])
    if mode == "agent" or force:
        cmd.append("--force")
    cmd.append(prompt)
    return cmd


def _completion(model: str, text: str) -> bytes:
    body = {
        "id": "chatcmpl-cli",
        "object": "chat.completion",
        "model": normalize_model(model) or model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }
    return json.dumps(body).encode()


def _error(status: int, message: str) -> tuple[int, bytes, dict[str, str]]:
    payload = json.dumps({"error": {"message": message, "type": "cli_lane"}}).encode()
    return status, payload, {"content-type": "application/json"}


def run_cursor_agent(
    messages: list[Any],
    model: str,
    timeout: float,
    body: dict[str, Any] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    binary = (os.environ.get("CURSOR_AGENT_BIN") or "cursor-agent").strip() or "cursor-agent"
    forge_cursor = parse_forge_cursor(body)
    workspace, err = validate_workspace(str(forge_cursor.get("workspace") or default_cli_cwd()))
    if err or workspace is None:
        return _error(400, err or "invalid workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    mode = str(forge_cursor.get("mode") or "ask")
    prompt = render_prompt(messages, mode=mode)
    if not prompt.strip():
        return _error(400, "messages required for CLI prompt")
    cmd = build_cursor_argv(
        binary=binary,
        model=model,
        workspace=workspace,
        prompt=prompt,
        forge_cursor=forge_cursor,
    )
    env = os.environ.copy()
    try:
        proc = subprocess.run(
            cmd,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return _error(503, "cursor-agent is not installed on the gateway host")
    except subprocess.TimeoutExpired:
        return _error(504, "cursor-agent timed out")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "cursor-agent failed").strip()[:500]
        return _error(502, detail)
    text = (proc.stdout or "").strip()
    if not text:
        return _error(502, "cursor-agent returned an empty reply")
    return 200, _completion(model, text), {"content-type": "application/json"}


def upstream_target() -> tuple[str, str]:
    """URL and bearer for the laptop CLI bridge. A file overrides the environment."""
    url = (os.environ.get("FORGE_LLM_CLI_UPSTREAM_URL") or "").strip().rstrip("/")
    token = (os.environ.get("FORGE_LLM_CLI_UPSTREAM_TOKEN") or "").strip()
    path = Path(os.environ.get("FORGE_LLM_CLI_UPSTREAM_FILE", "/data/cli-upstream.json"))
    if path.is_file():
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict):
            url = str(data.get("url") or url).strip().rstrip("/")
            token = str(data.get("token") or token).strip()
    return url, token


def _upstream_file() -> Path:
    return Path(os.environ.get("FORGE_LLM_CLI_UPSTREAM_FILE", "/data/cli-upstream.json"))


def queue_mode() -> bool:
    path = _upstream_file()
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and str(data.get("mode") or "") == "queue"


def _wait_queued(model: str, body: dict[str, Any], timeout: float) -> tuple[int, bytes, dict[str, str]]:
    """Park the completion on disk so a host that can run cursor-agent can answer it."""
    root = Path(os.environ.get("FORGE_LLM_CLI_QUEUE_DIR", "/data/cli-queue"))
    results = Path(os.environ.get("FORGE_LLM_CLI_RESULT_DIR", "/data/cli-result"))
    root.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    qid = uuid.uuid4().hex
    (root / f"{qid}.json").write_text(
        json.dumps({"id": qid, "model": normalize_model(model), "body": body})
    )
    target = results / f"{qid}.json"
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            if target.is_file():
                try:
                    data = json.loads(target.read_text())
                except (OSError, ValueError):
                    time.sleep(0.2)
                    continue
                status = int(data.get("status") or 502)
                content = data.get("content")
                if not isinstance(content, str):
                    content = json.dumps(content)
                return status, content.encode(), {"content-type": "application/json"}
            time.sleep(0.2)
        return _error(504, "CLI queue timed out")
    finally:
        for path in (root / f"{qid}.json", target):
            try:
                path.unlink()
            except OSError:
                pass


async def openai_chat_via_cli(
    *,
    model: str,
    body: dict[str, Any],
    timeout: float = 180.0,
) -> tuple[int, bytes, dict[str, str]]:
    fc = parse_forge_cursor(body)
    if fc.get("timeout_s") is not None:
        timeout = float(fc["timeout_s"])
    if queue_mode():
        return await asyncio.to_thread(_wait_queued, model, body, timeout)
    upstream, token = upstream_target()
    if upstream:
        url = upstream if upstream.endswith("/chat/completions") else f"{upstream}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = {**body, "model": normalize_model(model)}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=20.0)) as client:
                response = await client.post(url, content=json.dumps(payload).encode(), headers=headers)
        except httpx.HTTPError as ex:
            return _error(503, f"CLI upstream unreachable: {type(ex).__name__}")
        media = response.headers.get("content-type", "application/json")
        return response.status_code, response.content, {"content-type": media}

    messages = body.get("messages") if isinstance(body.get("messages"), list) else []
    return await asyncio.to_thread(run_cursor_agent, messages, model, timeout, body)


async def respond_cli_chat(
    *,
    ctx: ForgeContext,
    body: dict[str, Any],
    model: str,
    timeout: float,
    path: str = "/v1/chat/completions",
) -> Response:
    t0 = time.perf_counter()
    status, content, cli_hdrs = await openai_chat_via_cli(model=model, body=body, timeout=timeout)
    record_cli_completion(
        ctx=ctx,
        body=body,
        model=model,
        status=status,
        content=content,
        t0=t0,
        path=path,
        served_model=cli_model_id(model),
    )
    media = cli_hdrs.get("content-type", "application/json")
    return Response(content=content, status_code=status, media_type=media)


def cli_chat_timeout(body: dict[str, Any]) -> float:
    fc = parse_forge_cursor(body)
    if fc.get("timeout_s") is not None:
        return float(fc["timeout_s"])
    try:
        return float(body.get("timeout") or DEFAULT_HOLD_TIMEOUT_SEC)
    except (TypeError, ValueError):
        return float(DEFAULT_HOLD_TIMEOUT_SEC)


def assert_cli_async_allowed(body: dict[str, Any], ctx: ForgeContext) -> None:
    if cli_requires_async(body) and not ctx.async_job:
        raise HTTPException(
            status_code=400,
            detail=(
                "CLI agent or long timeout requires X-Forge-Async: 1 "
                "and webhook headers for async jobs"
            ),
        )