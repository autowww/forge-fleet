"""DCE-G3 — resolver backends.

``ResolverBackend.complete(prompt, *, max_tokens, seed) -> BackendResult``. Three implementations:

* ``NullBackend``           — answers ``abstain`` for every prompt; zero tokens; lets the pipeline run with no model.
* ``RecordedBackend``       — prompt-digest-pinned recordings; a miss raises ``RecordingMiss`` (the resolver fails closed).
* ``OpenAICompatibleBackend`` — ``POST {base_url}/chat/completions`` (urllib). Constructed only from an explicit
  ``OpenAICompatibleConfig``; ``from_env()`` is the sole place environment variables are read, and nothing here runs at
  import time. Tests never construct a live client against the network.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

PROMPT_DIGEST_PREFIX = "sha256:"


def prompt_digest(prompt: str) -> str:
    return PROMPT_DIGEST_PREFIX + hashlib.sha256(prompt.encode("utf-8", "surrogatepass")).hexdigest()


@dataclass(frozen=True)
class BackendResult:
    text: str
    model_id: str
    kind: str                                   # null | recorded | openai_compatible
    input_tokens: int
    output_tokens: int
    elapsed_ms: float
    finish_reason: str = "stop"
    runtime: dict[str, Any] = field(default_factory=dict)   # model/quantization/context/hardware/serving as recorded


class ResolverBackend(Protocol):
    kind: str
    model_id: str

    def complete(self, prompt: str, *, max_tokens: int, seed: int) -> BackendResult: ...

    def describe(self) -> dict[str, Any]: ...


class BackendError(RuntimeError):
    """Nonresponse / transport failure; the resolver records a REJECT finding and never retries beyond the budget."""


class RecordingMiss(BackendError):
    pass


class NullBackend:
    kind = "null"
    model_id = "null"

    def complete(self, prompt: str, *, max_tokens: int, seed: int) -> BackendResult:
        return BackendResult(json.dumps({"abstain": True, "reason": "null backend: no model configured"}), self.model_id, self.kind, 0, 0, 0.0)

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "model_id": self.model_id, "runtime": {}, "settings": {}}


@dataclass
class Recording:
    prompt_digest: str
    response_text: str
    model_id: str = "recorded"
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_ms: float = 0.0
    runtime: dict[str, Any] = field(default_factory=dict)


class RecordedBackend:
    """Deterministic replay. ``strict`` (default) raises on an unknown prompt digest; the resolver turns that into a
    fail-closed finding. Recordings establish *verifier* behaviour, never model comprehension."""
    kind = "recorded"

    def __init__(self, recordings: list[Recording] | dict[str, Any], *, strict: bool = True, model_id: str = "recorded") -> None:
        self._by_digest: dict[str, Recording] = {}
        if isinstance(recordings, dict):
            recordings = [Recording(**r) if isinstance(r, dict) else r for r in recordings.get("recordings", [])]
        for r in recordings:
            self._by_digest[r.prompt_digest] = r
        self.strict = strict
        self.model_id = model_id
        self.calls: list[str] = []

    @classmethod
    def from_json_file(cls, path: str, **kw: Any) -> "RecordedBackend":
        with open(path, "r", encoding="utf-8") as fh:
            return cls(json.load(fh), **kw)

    def complete(self, prompt: str, *, max_tokens: int, seed: int) -> BackendResult:
        d = prompt_digest(prompt)
        self.calls.append(d)
        r = self._by_digest.get(d)
        if r is None:
            if self.strict:
                raise RecordingMiss(f"no recording for prompt {d[:23]}…")
            return BackendResult(json.dumps({"abstain": True, "reason": "recording miss"}), self.model_id, self.kind, 0, 0, 0.0)
        return BackendResult(r.response_text, r.model_id or self.model_id, self.kind, r.input_tokens, r.output_tokens, r.elapsed_ms,
                             runtime=dict(r.runtime))

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "model_id": self.model_id, "runtime": {"recordings": len(self._by_digest), "strict": self.strict}, "settings": {}}


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    base_url: str                               # e.g. http://127.0.0.1:11434/v1  (no default: the operator sets it)
    model: str
    api_key: Optional[str] = None
    timeout_s: float = 60.0
    temperature: float = 0.0
    seed: int = 0
    extra_runtime: dict[str, Any] = field(default_factory=dict)   # quantization / context / hardware, operator-provided

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "OpenAICompatibleConfig":
        """Explicit opt-in: FORGE_SQUID_G3_LLM_BASE_URL and FORGE_SQUID_G3_MODEL must both be set. Never called implicitly."""
        base = env.get("FORGE_SQUID_G3_LLM_BASE_URL", "").strip()
        model = env.get("FORGE_SQUID_G3_MODEL", "").strip()
        if not base or not model:
            raise ValueError("FORGE_SQUID_G3_LLM_BASE_URL and FORGE_SQUID_G3_MODEL are required for a live backend")
        if not base.startswith(("http://", "https://")):
            raise ValueError("base_url must be http(s)")
        return cls(base, model, env.get("FORGE_SQUID_G3_API_KEY") or None, float(env.get("FORGE_SQUID_G3_TIMEOUT_S", "60")),
                   extra_runtime={k[len("FORGE_SQUID_G3_RT_"):].lower(): v for k, v in env.items() if k.startswith("FORGE_SQUID_G3_RT_")})


class OpenAICompatibleBackend:
    kind = "openai_compatible"

    def __init__(self, config: OpenAICompatibleConfig, *, opener: Any = None) -> None:
        self.config = config
        self.model_id = config.model
        self._open = opener or urllib.request.urlopen     # injectable for tests; the default is the real transport

    def complete(self, prompt: str, *, max_tokens: int, seed: int) -> BackendResult:
        body = {"model": self.config.model, "messages": [{"role": "user", "content": prompt}], "temperature": self.config.temperature,
                "max_tokens": max_tokens, "seed": seed if seed else self.config.seed, "stream": False,
                "response_format": {"type": "json_object"}}
        req = urllib.request.Request(self.config.base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {})},
                                     method="POST")
        t0 = time.perf_counter()
        try:
            with self._open(req, timeout=self.config.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as ex:
            raise BackendError(f"backend transport failure: {type(ex).__name__}") from ex
        elapsed = (time.perf_counter() - t0) * 1000.0
        try:
            choice = payload["choices"][0]
            text = choice["message"]["content"]
            finish = choice.get("finish_reason", "stop") or "stop"
        except (KeyError, IndexError, TypeError) as ex:
            raise BackendError("backend response missing choices[0].message.content") from ex
        usage = payload.get("usage") or {}
        runtime = {"served_model": payload.get("model", self.config.model), "system_fingerprint": payload.get("system_fingerprint"),
                   "temperature": self.config.temperature, "seed": body["seed"], **self.config.extra_runtime}
        return BackendResult(text if isinstance(text, str) else "", payload.get("model", self.config.model), self.kind,
                             int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0), round(elapsed, 3), finish, runtime)

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "model_id": self.model_id,
                "runtime": {"base_url_host": self.config.base_url.split("//", 1)[-1].split("/", 1)[0], **self.config.extra_runtime},
                "settings": {"temperature": self.config.temperature, "seed": self.config.seed, "timeout_s": self.config.timeout_s}}
