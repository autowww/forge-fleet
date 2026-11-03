"""Runner configuration and adapter protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

RunnerKind = str  # ollama | llama_cpp | vllm


@dataclass(frozen=True)
class ArtifactPin:
    runner_model_id: str
    catalog_alias: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class ExternalRunnerConfig:
    openwebui_base_url: str = ""
    chatgpt_model: str = "granite-chatgpt-primary"
    gemini_model: str = "granite-gemini-primary"
    max_concurrent: int = 4


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
    free_vram_gb: float = 4.0
    artifact_pins: tuple[ArtifactPin, ...] = ()
    coalesce_sec: float = 3.0
    starve_sec: float = 120.0
    catalog_path: str | None = None
    external: ExternalRunnerConfig = field(default_factory=ExternalRunnerConfig)

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

    async def resident_models(self) -> list[str]: ...

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
