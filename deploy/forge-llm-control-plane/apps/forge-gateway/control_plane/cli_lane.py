"""Composer completions through the Cursor CLI.

``composer`` and ``composer-*`` never go to Ollama. When
``FORGE_LLM_CLI_UPSTREAM_URL`` is set, the gateway forwards the OpenAI body
there (the laptop CLI bridge). Otherwise it runs ``cursor-agent`` on this host.
The logged-in CLI does not need ``CURSOR_API_KEY``.
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

_PREFIX = "forge-llm."


def normalize_model(model: str) -> str:
    name = (model or "").strip()
    if name.startswith(_PREFIX):
        name = name[len(_PREFIX) :]
    return name


def is_cli_model(model: str) -> bool:
    name = normalize_model(model).lower()
    return name == "composer" or name.startswith("composer-")


def cli_model_id(model: str) -> str:
    name = normalize_model(model)
    if name.lower() == "composer":
        return "composer-2.5"
    return name


def render_prompt(messages: list[Any]) -> str:
    parts: list[str] = [
        "Reply with only the assistant message. Do not use tools. Do not edit files."
    ]
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
    return "\n\n".join(parts)


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


def run_cursor_agent(messages: list[Any], model: str, timeout: float) -> tuple[int, bytes, dict[str, str]]:
    binary = (os.environ.get("CURSOR_AGENT_BIN") or "cursor-agent").strip() or "cursor-agent"
    cwd = Path(os.environ.get("FORGE_LLM_CLI_CWD", "/tmp/forge-llm-cli"))
    cwd.mkdir(parents=True, exist_ok=True)
    prompt = render_prompt(messages)
    cmd = [
        binary,
        "--print",
        "--trust",
        "--mode",
        "ask",
        "--model",
        cli_model_id(model),
        "--output-format",
        "text",
        "--workspace",
        str(cwd),
        prompt,
    ]
    env = os.environ.copy()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
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
    return await asyncio.to_thread(run_cursor_agent, messages, model, timeout)
