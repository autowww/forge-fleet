"""Load and validate runner.yaml."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import yaml

from runners.base import ArtifactPin, ExternalRunnerConfig, MeasuredProfile, RunnerConfig

ALLOWED_RUNTIME_KEYS = frozenset(
    {
        "OLLAMA_HOST",
        "OLLAMA_MAX_LOADED_MODELS",
        "OLLAMA_NUM_PARALLEL",
        "OLLAMA_KEEP_ALIVE",
    }
)
ALLOWED_KINDS = frozenset({"ollama", "llama_cpp", "vllm"})

_DEFAULT_MODE_MODELS: dict[str, str] = {
    "interactive": "ctx-unlim-qwen3-8b:latest",
    "task_code": "qwen3:30b-a3b",
    "struct_json": "ctx-unlim-qwen3-8b:latest",
    "reason_short": "qwen3:30b-a3b",
    "long_ctx": "ctx-unlim-qwen3-14b:latest",
    "codegen_loop": "ctx-unlim-granite41-8b:latest",
    "embed": "nomic-embed-text:latest",
    "batch_eval": "ctx-unlim-qwen3-14b:latest",
}

_DEFAULT_QUARANTINE = frozenset(
    {"ctx-unlim-qwen25-coder-7b:latest", "qwen2.5-coder:7b"}
)

_cached: RunnerConfig | None = None


def _default_config() -> RunnerConfig:
    return RunnerConfig(
        kind="ollama",
        bind="127.0.0.1:11434",
        runtime={},
        models=tuple(_DEFAULT_MODE_MODELS.values()),
        exclusive_slot=False,
        mode_models=dict(_DEFAULT_MODE_MODELS),
        quarantined_models=_DEFAULT_QUARANTINE,
        classifier_model="ibm/granite4:tiny-h",
        source_path=None,
        free_vram_gb=4.0,
        artifact_pins=(),
        coalesce_sec=3.0,
        starve_sec=120.0,
        catalog_path=None,
        external=ExternalRunnerConfig(),
    )


def _opt_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _opt_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _opt_str(v: Any) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def _parse_measured(raw: Any) -> MeasuredProfile | None:
    if not isinstance(raw, dict) or not raw:
        return None
    return MeasuredProfile(
        peak_vram_mib=_opt_int(raw.get("peak_vram_mib")),
        context_length=_opt_int(raw.get("context_length")),
        active_requests=_opt_int(raw.get("active_requests")),
        p95_latency_ms=_opt_int(raw.get("p95_latency_ms")),
        decode_tokens_per_second=_opt_float(raw.get("decode_tokens_per_second")),
        task_quality_score=_opt_float(raw.get("task_quality_score")),
        runtime_version=_opt_str(raw.get("runtime_version")),
        gpu_uuid=_opt_str(raw.get("gpu_uuid")),
    )


_RUNTIME_PROBE_VALUES = frozenset({"unprobed", "passed", "failed"})


def _parse_artifact_pins(raw: Any) -> tuple[ArtifactPin, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[ArtifactPin] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("runner_model_id") or item.get("model") or "").strip()
        if not mid:
            continue
        probe = str(item.get("runtime_probe") or "unprobed").strip().lower()
        if probe not in _RUNTIME_PROBE_VALUES:
            raise ValueError(f"artifact pin {mid!r}: runtime_probe must be one of {sorted(_RUNTIME_PROBE_VALUES)}")
        out.append(
            ArtifactPin(
                runner_model_id=mid,
                catalog_alias=_opt_str(item.get("catalog_alias")),
                enabled=bool(item.get("enabled", True)),
                model_revision=_opt_str(item.get("model_revision")),
                weight_file_sha256=_opt_str(item.get("weight_file_sha256")),
                precision=_opt_str(item.get("precision")),
                license_approval=bool(item.get("license_approval", False)),
                runtime_probe=probe,
                tier_note=_opt_str(item.get("tier_note")),
                measured=_parse_measured(item.get("measured")),
            )
        )
    return tuple(out)


def _parse_external(raw: Any) -> ExternalRunnerConfig:
    if not isinstance(raw, dict):
        return ExternalRunnerConfig()
    return ExternalRunnerConfig(
        openwebui_base_url=str(raw.get("openwebui_base_url") or "").strip(),
        chatgpt_model=str(raw.get("chatgpt_model") or "granite-chatgpt-primary").strip(),
        gemini_model=str(raw.get("gemini_model") or "granite-gemini-primary").strip(),
        max_concurrent=max(1, int(raw.get("max_concurrent") or 4)),
    )


def _resolve_catalog_path(data: dict[str, Any], source: str | None) -> str | None:
    raw = data.get("catalog_path")
    if raw:
        p = Path(str(raw).strip()).expanduser()
        if p.is_file():
            return str(p)
        if source:
            rel = (Path(source).resolve().parent / raw).resolve()
            if rel.is_file():
                return str(rel)
    if source:
        repo = Path(source).resolve().parent.parent / "catalog" / "forge_llm_catalog_2026-11-03.json"
        if repo.is_file():
            return str(repo)
    bundled = Path(__file__).resolve().parents[3] / "configs" / "catalog" / "forge_llm_catalog_2026-11-03.json"
    if bundled.is_file():
        return str(bundled)
    return None


def resolve_runner_path() -> Path | None:
    raw = (os.environ.get("FORGE_LLM_RUNNER_CONFIG") or "").strip()
    if raw:
        p = Path(raw).expanduser()
        return p if p.is_file() else None
    for candidate in (
        Path("/config/runner.yaml"),
        Path("/etc/forge-llm/runner.yaml"),
    ):
        if candidate.is_file():
            return candidate
    # Repo layout: forge-llm/configs/runner.granite.yaml from gateway cwd
    repo_root = Path(__file__).resolve().parents[3]
    for name in ("runner.yaml", "runner.granite.yaml", "runner.example.yaml"):
        p = repo_root / "configs" / name
        if p.is_file():
            return p
    return None


def _validate_bind(bind: str) -> None:
    host = bind.rsplit(":", 1)[0]
    allow_remote = (os.environ.get("FORGE_LLM_ALLOW_REMOTE_BIND") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not allow_remote and host not in ("127.0.0.1", "localhost"):
        raise ValueError(f"runner bind must be loopback, got {bind!r}")


def _parse_raw(data: dict[str, Any], source: str | None) -> RunnerConfig:
    kind = str(data.get("kind") or "ollama").strip()
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"unknown runner kind: {kind!r}")
    bind = str(data.get("bind") or "127.0.0.1:11434").strip()
    _validate_bind(bind)
    runtime_raw = data.get("runtime") or {}
    if not isinstance(runtime_raw, dict):
        raise ValueError("runtime must be a mapping")
    runtime: dict[str, str] = {}
    for k, v in runtime_raw.items():
        key = str(k).strip()
        if key not in ALLOWED_RUNTIME_KEYS:
            raise ValueError(f"runtime key not allowed: {key!r}")
        runtime[key] = str(v).strip()
    if "OLLAMA_HOST" in runtime and runtime["OLLAMA_HOST"] not in (
        "127.0.0.1:11434",
        "127.0.0.1",
    ):
        if (os.environ.get("FORGE_LLM_ALLOW_REMOTE_BIND") or "").strip().lower() not in (
            "1",
            "true",
            "yes",
        ):
            raise ValueError("OLLAMA_HOST must stay on loopback for shared Open WebUI bypass")
    exclusive = bool(data.get("exclusive_slot", False))
    mode_models = dict(_DEFAULT_MODE_MODELS)
    mm = data.get("mode_models")
    if isinstance(mm, dict):
        for mk, mv in mm.items():
            mode_models[str(mk).strip()] = str(mv).strip()
    quarantine = set(_DEFAULT_QUARANTINE)
    qlist = data.get("quarantined_models")
    if isinstance(qlist, list):
        quarantine = {str(x).strip() for x in qlist if str(x).strip()}
    models_list = data.get("models")
    models: tuple[str, ...] = tuple(_DEFAULT_MODE_MODELS.values())
    if isinstance(models_list, list):
        models = tuple(str(x).strip() for x in models_list if str(x).strip())
    classifier = str(data.get("classifier_model") or "ibm/granite4:tiny-h").strip()
    free_vram = float(data.get("free_vram_gb") or 4.0)
    coalesce = float(data.get("coalesce_sec") or 3.0)
    starve = float(data.get("starve_sec") or 120.0)
    pins = _parse_artifact_pins(data.get("artifact_pins"))
    external = _parse_external(data.get("external"))
    catalog_path = _resolve_catalog_path(data, source)
    max_active = max(1, int(data.get("max_active_requests") or 1))
    max_queue = _opt_int(data.get("max_queue_depth"))
    if max_queue is not None and max_queue < 1:
        raise ValueError("max_queue_depth must be >= 1 when set")
    headroom = float(data.get("headroom_ratio") if data.get("headroom_ratio") is not None else 0.15)
    if not 0.0 <= headroom < 1.0:
        raise ValueError("headroom_ratio must be in [0, 1)")
    return RunnerConfig(
        kind=kind,
        bind=bind,
        runtime=runtime,
        models=models,
        exclusive_slot=exclusive,
        mode_models=mode_models,
        quarantined_models=frozenset(quarantine),
        classifier_model=classifier,
        source_path=source,
        free_vram_gb=free_vram,
        artifact_pins=pins,
        coalesce_sec=coalesce,
        starve_sec=starve,
        catalog_path=catalog_path,
        external=external,
        max_active_requests=max_active,
        max_queue_depth=max_queue,
        headroom_ratio=headroom,
    )


def load_runner_config(*, reload: bool = False) -> RunnerConfig:
    global _cached
    if _cached is not None and not reload:
        return _cached
    path = resolve_runner_path()
    if path is None:
        _cached = _default_config()
        return _cached
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"runner config must be a mapping: {path}")
    _cached = _parse_raw(data, str(path))
    return _cached


def reset_runner_cache() -> None:
    global _cached
    _cached = None


def config_hash(cfg: RunnerConfig | None = None) -> str:
    c = cfg or load_runner_config()
    blob = yaml.safe_dump(
        {
            "kind": c.kind,
            "bind": c.bind,
            "runtime": dict(sorted(c.runtime.items())),
            "exclusive_slot": c.exclusive_slot,
            "mode_models": dict(sorted(c.mode_models.items())),
            "quarantined_models": sorted(c.quarantined_models),
            "models": list(c.models),
            "classifier_model": c.classifier_model,
            "free_vram_gb": c.free_vram_gb,
            "coalesce_sec": c.coalesce_sec,
            "starve_sec": c.starve_sec,
            "max_active_requests": c.max_active_requests,
            "max_queue_depth": c.max_queue_depth,
            "headroom_ratio": c.headroom_ratio,
            "artifact_pins": [
                [p.runner_model_id, p.catalog_alias, p.enabled, p.model_revision, p.weight_file_sha256]
                for p in c.artifact_pins
            ],
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def render_systemd_dropin(runtime: dict[str, str]) -> str:
    """systemd drop-in Environment= lines for present runtime keys only."""
    lines = ["[Service]"]
    for key in sorted(runtime.keys()):
        if key not in ALLOWED_RUNTIME_KEYS:
            continue
        val = runtime[key].replace('"', '\\"')
        lines.append(f'Environment="{key}={val}"')
    return "\n".join(lines) + "\n"
