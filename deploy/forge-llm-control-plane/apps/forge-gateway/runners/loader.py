"""Load and validate runner.yaml."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import yaml

from runners.base import RunnerConfig

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
    )


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
