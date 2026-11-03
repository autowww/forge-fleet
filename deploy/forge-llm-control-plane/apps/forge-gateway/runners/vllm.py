"""vLLM OpenAI server adapter (/v1 only)."""

from __future__ import annotations

from typing import Any

import httpx

from runners.base import NativeApiUnsupported, RunnerConfig
from runners.llama_cpp import LlamaCppAdapter


class VllmAdapter(LlamaCppAdapter):
    kind = "vllm"

    def __init__(self, config: RunnerConfig, *, base_url: str) -> None:
        super().__init__(config, base_url=base_url)

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self.base_url}/health")
                if r.status_code < 400:
                    return {"ok": True}
                r2 = await client.get(f"{self.base_url}/v1/models")
                if r2.status_code < 400:
                    return {"ok": True}
        except httpx.RequestError as exc:
            return {"ok": False, "error": str(exc)[:200]}
        return {"ok": False, "status_code": r.status_code}

    async def native_request(
        self,
        method: str,
        path: str,
        body: bytes,
        *,
        timeout: float = 600.0,
    ) -> tuple[int, bytes, dict[str, str]]:
        raise NativeApiUnsupported(self.kind)
