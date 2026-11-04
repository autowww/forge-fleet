"""Runner configuration and adapter protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

RunnerKind = str  # ollama | llama_cpp | vllm


@dataclass(frozen=True)
class MeasuredProfile:
    """Catalog layer 4 — measured deployment profile (artifact × engine × GPU)."""

    peak_vram_mib: int | None = None
    context_length: int | None = None
    active_requests: int | None = None
    p95_latency_ms: int | None = None
    decode_tokens_per_second: float | None = None
    task_quality_score: float | None = None
    runtime_version: str | None = None
    gpu_uuid: str | None = None


@dataclass(frozen=True)
class ArtifactPin:
    """Catalog layer 2 — pinned runtime artifact (Ollama tag / GGUF / AWQ) on this host."""

    runner_model_id: str
    catalog_alias: str | None = None
    enabled: bool = True
    model_revision: str | None = None
    weight_file_sha256: str | None = None
    precision: str | None = None
    license_approval: bool = False
    runtime_probe: str = "unprobed"  # unprobed | passed | failed
    tier_note: str | None = None
    measured: MeasuredProfile | None = None

    def promotion_missing(self) -> list[str]:
        """Required promotion metrics (catalog ``metrics_required_for_promotion``) not yet supplied."""
        missing: list[str] = []
        if not self.model_revision:
            missing.append("model_revision")
        if not self.weight_file_sha256:
            missing.append("weight_file_sha256")
        if self.runtime_probe != "passed":
            missing.append("runtime_version")
        m = self.measured
        if m is None or m.peak_vram_mib is None:
            missing.append("measured_peak_vram_mib")
        if m is None or m.context_length is None:
            missing.append("context_length")
        if m is None or m.active_requests is None:
            missing.append("active_requests")
        if m is None or m.p95_latency_ms is None:
            missing.append("p95_latency_ms")
        if m is None or m.task_quality_score is None:
            missing.append("task_quality_score")
        if not self.license_approval:
            missing.append("license_approval")
        return missing

    @property
    def deployment_authorized(self) -> bool:
        """True only when every promotion metric is present and license is approved."""
        return not self.promotion_missing()


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
    max_active_requests: int = 1
    max_queue_depth: int | None = None
    headroom_ratio: float = 0.15

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
