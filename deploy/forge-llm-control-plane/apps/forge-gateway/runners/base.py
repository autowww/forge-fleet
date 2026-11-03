"""Runner configuration and adapter protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

RunnerKind = str  # ollama | llama_cpp | vllm


class NativeApiUnsupported(Exception):
    """Raised when /api/* is used with a non-Ollama runner."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"native Ollama API unsupported for runner kind={kind}")
        self.kind = kind


@dataclass(frozen=True)
class RunnerConfig:
    kind: RunnerKind
    bind: str
    runtime: dict[str, str] = field(default_factory=dict)
    models: tuple[str, ...] = ()
    exclusive_slot: bool = False
    mode_models: dict[str, str] = field(default_factory=dict)
    quarantined_models: frozenset[str] = frozenset()
    classifier_model: str = "ibm/granite4:tiny-h"
    source_path: str | None = None

    def upstream_base_url(self) -> str:
        """HTTP base for adapter calls (host:port from bind)."""
        host, _, port = self.bind.partition(":")
        if not port:
            port = "11434"
        return f"http://{host}:{port}"


class RunnerAdapter(Protocol):
    kind: str
    config: RunnerConfig

    async def health(self) -> dict[str, Any]: ...

    async def list_models(self) -> list[str]: ...

    async def warm(self, model: str) -> tuple[bool, str | None]: ...

    async def unload(self, model: str) -> None: ...

    async def openai_request(
        self,
        method: str,
        path: str,
        body: bytes,
        *,
        timeout: float = 600.0,
    ) -> tuple[int, bytes, dict[str, str]]: ...

    async def native_request(
        self,
        method: str,
        path: str,
        body: bytes,
        *,
        timeout: float = 600.0,
    ) -> tuple[int, bytes, dict[str, str]]: ...
