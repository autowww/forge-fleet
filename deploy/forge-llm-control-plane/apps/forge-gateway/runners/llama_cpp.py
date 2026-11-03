"""llama.cpp OpenAI server adapter (/v1 only)."""

from __future__ import annotations

from typing import Any

import httpx

from runners.base import NativeApiUnsupported, RunnerConfig
from runners.ollama import OllamaAdapter


class LlamaCppAdapter(OllamaAdapter):
    kind = "llama_cpp"

    def __init__(self, config: RunnerConfig, *, base_url: str) -> None:
        super().__init__(config, base_url=base_url)

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self.base_url}/v1/models")
                if r.status_code < 400:
                    return {"ok": True}
        except httpx.RequestError as exc:
            return {"ok": False, "error": str(exc)[:200]}
        return {"ok": False, "status_code": r.status_code}

    async def resident_models(self) -> list[str]:
        names = await self.list_models()
        return names[:1] if names else []

    async def warm(self, model: str) -> tuple[bool, str | None]:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        status, _, _ = await self.openai_request(
            "POST",
            "/v1/chat/completions",
            __import__("json").dumps(body).encode(),
            timeout=120.0,
        )
        if status >= 400:
            return False, f"warm failed HTTP {status}"
        return True, None

    async def native_request(
        self,
        method: str,
        path: str,
        body: bytes,
        *,
        timeout: float = 600.0,
    ) -> tuple[int, bytes, dict[str, str]]:
        raise NativeApiUnsupported(self.kind)
