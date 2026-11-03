"""Ollama runner adapter."""

from __future__ import annotations

import json
from typing import Any

import httpx

from runners.base import RunnerConfig


class OllamaAdapter:
    kind = "ollama"

    def __init__(self, config: RunnerConfig, *, base_url: str) -> None:
        self.config = config
        self.base_url = base_url.rstrip("/")

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self.base_url}/api/version")
                if r.status_code < 400:
                    return {"ok": True, "version": r.json()}
        except httpx.RequestError as exc:
            return {"ok": False, "error": str(exc)[:200]}
        return {"ok": False, "status_code": r.status_code}

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{self.base_url}/api/tags")
            if r.status_code >= 400:
                return []
            data = r.json()
            models = data.get("models") or []
            out: list[str] = []
            for m in models:
                if isinstance(m, dict) and m.get("name"):
                    out.append(str(m["name"]))
            return out

    async def resident_models(self) -> list[str]:
        url = f"{self.base_url}/api/ps"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url)
                if r.status_code >= 400:
                    return []
                data = r.json()
        except httpx.RequestError:
            return []
        models = data.get("models") or []
        out: list[str] = []
        for m in models:
            if isinstance(m, dict) and m.get("name"):
                out.append(str(m["name"]))
        return out

    async def warm(self, model: str) -> tuple[bool, str | None]:
        url = f"{self.base_url}/api/generate"
        payload: dict[str, Any] = {
            "model": model,
            "prompt": "ping",
            "stream": False,
            "options": {"num_predict": 1, "num_ctx": 512},
        }
        if "qwen" in model.lower():
            payload["think"] = False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
                r = await client.post(url, json=payload)
                if r.status_code >= 400:
                    return False, r.text[:500]
        except httpx.RequestError as exc:
            return False, str(exc)[:500]
        return True, None

    async def unload(self, model: str) -> None:
        if not self.config.exclusive_slot:
            return
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": "",
            "stream": False,
            "keep_alive": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(url, json=payload)
        except httpx.RequestError:
            pass

    async def openai_request(
        self,
        method: str,
        path: str,
        body: bytes,
        *,
        timeout: float = 600.0,
    ) -> tuple[int, bytes, dict[str, str]]:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=30.0)) as client:
            r = await client.request(
                method,
                url,
                content=body,
                headers={"Content-Type": "application/json"},
            )
            hdrs = {k.lower(): v for k, v in r.headers.items()}
            return r.status_code, r.content, hdrs

    async def native_request(
        self,
        method: str,
        path: str,
        body: bytes,
        *,
        timeout: float = 600.0,
    ) -> tuple[int, bytes, dict[str, str]]:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=30.0)) as client:
            r = await client.request(
                method,
                url,
                content=body,
                headers={"Content-Type": "application/json"},
            )
            hdrs = {k.lower(): v for k, v in r.headers.items()}
            return r.status_code, r.content, hdrs
