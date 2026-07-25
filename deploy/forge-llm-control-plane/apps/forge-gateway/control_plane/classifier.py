"""Mode classification: rules first, optional tiny LLM fallback."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import httpx

from control_plane.config import CLASSIFIER_MODEL, OLLAMA_BASE
from control_plane.modes import ALL_MODES, ModeId, ModeResolution, model_for_mode, normalize_mode

_cache: dict[str, tuple[float, ModeResolution]] = {}
_CACHE_TTL = 300.0


def _cache_key(consumer: str, text: str) -> str:
    h = hashlib.sha256(f"{consumer}:{text[:2000]}".encode()).hexdigest()[:32]
    return h


def classify_by_rules(
    *,
    path: str,
    body: dict[str, Any] | None,
    consumer: str,
) -> ModeResolution | None:
    if "/embeddings" in path:
        return ModeResolution("embed", model_for_mode("embed"), "classify_rules")
    if not body:
        return ModeResolution("interactive", model_for_mode("interactive"), "classify_rules")
    if body.get("response_format") or body.get("response_format") == {"type": "json_object"}:
        return ModeResolution("struct_json", model_for_mode("struct_json"), "classify_rules")
    messages = body.get("messages") or []
    text = " ".join(
        str(m.get("content", "")) for m in messages if isinstance(m, dict)
    )
    est_chars = len(text)
    if est_chars > 12000:
        return ModeResolution("long_ctx", model_for_mode("long_ctx"), "classify_rules")
    if any(k in text.lower() for k in ("def ", "class ", "pytest", "import ", "fix the bug")):
        return ModeResolution("task_code", model_for_mode("task_code"), "classify_rules")
    if any(k in text.lower() for k in ("pdf", "extractor", "structure_discover", "synthesize")):
        return ModeResolution("codegen_loop", model_for_mode("codegen_loop"), "classify_rules")
    if consumer in ("dark-factory", "forge-dark-factory"):
        return ModeResolution("task_code", model_for_mode("task_code"), "classify_rules")
    return None


async def classify_by_llm(*, consumer: str, text: str) -> ModeResolution | None:
    key = _cache_key(consumer, text)
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < _CACHE_TTL:
        return hit[1]
    prompt = (
        "Classify this LLM request into exactly one mode. "
        f"Modes: {', '.join(ALL_MODES)}. "
        'Reply JSON only: {"mode":"<mode>"}. '
        f"Request preview: {text[:800]}"
    )
    url = f"{OLLAMA_BASE}/api/chat"
    payload = {
        "model": CLASSIFIER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"num_predict": 32, "temperature": 0},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=payload)
            if r.status_code >= 400:
                return None
            data = r.json()
            content = (data.get("message") or {}).get("content") or ""
            obj = json.loads(content.strip())
            mode = normalize_mode(str(obj.get("mode", "")))
            if not mode:
                return None
            res = ModeResolution(mode, model_for_mode(mode), "classify_llm")
            _cache[key] = (now, res)
            return res
    except (httpx.RequestError, json.JSONDecodeError, KeyError, TypeError):
        return None


async def resolve_mode(
    *,
    header_mode: ModeId | None,
    body_mode: str | None,
    path: str,
    body: dict[str, Any] | None,
    consumer: str,
) -> ModeResolution:
    if header_mode:
        return ModeResolution(header_mode, model_for_mode(header_mode), "header")
    bm = normalize_mode(body_mode)
    if bm:
        return ModeResolution(bm, model_for_mode(bm), "body")
    ruled = classify_by_rules(path=path, body=body, consumer=consumer)
    if ruled:
        return ruled
    text = ""
    if body and isinstance(body.get("messages"), list):
        text = " ".join(
            str(m.get("content", "")) for m in body["messages"] if isinstance(m, dict)
        )
    llm = await classify_by_llm(consumer=consumer, text=text)
    if llm:
        return llm
    return ModeResolution("interactive", model_for_mode("interactive"), "default")
