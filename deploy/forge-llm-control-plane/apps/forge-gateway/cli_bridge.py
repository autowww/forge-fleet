#!/usr/bin/env python3
"""OpenAI chat bridge on the operator laptop. CLI models -> cursor-agent."""

from __future__ import annotations

import json
import os
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from control_plane.cli_lane import cli_chat_timeout, is_cli_model, openai_chat_via_cli
import asyncio


def _token() -> str:
    return (os.environ.get("FORGE_LLM_CLI_BRIDGE_TOKEN") or "").strip()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _unauthorized(self) -> None:
        body = b'{"error":{"message":"unauthorized"}}'
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = _token()
        header = self.headers.get("Authorization", "")
        provided = header[7:] if header.startswith("Bearer ") else ""
        return bool(expected) and hmac.compare_digest(provided, expected)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self.send_error(404)
            return
        if not self._authorized():
            self._unauthorized()
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except ValueError:
            self.send_error(400)
            return
        model = str(body.get("model") or "composer")
        if not is_cli_model(model):
            payload = b'{"error":{"message":"bridge accepts CLI models only"}}'
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        timeout = cli_chat_timeout(body if isinstance(body, dict) else {})

        async def _run() -> tuple[int, bytes, dict[str, str]]:
            return await openai_chat_via_cli(model=model, body=body, timeout=timeout)

        status, content, _hdrs = asyncio.run(_run())
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    if not _token():
        raise SystemExit("FORGE_LLM_CLI_BRIDGE_TOKEN is required")
    host = os.environ.get("FORGE_LLM_CLI_BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("FORGE_LLM_CLI_BRIDGE_PORT", "8766"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()