"""Pinned canonicalization and plan hashing.

Canonical form (``NORMALIZATION_VERSION``):

- JSON object keys sorted lexicographically by Unicode code point.
- No insignificant whitespace; separators ``,`` and ``:``.
- UTF-8 output, non-ASCII preserved (``ensure_ascii=False``).
- Every string NFC-normalized before serialization.
- Only ``int`` numbers are permitted in hashed payloads; ``float`` is rejected to avoid
  representation ambiguity. Booleans and ``null`` are permitted.
- Arrays are **order-sensitive**. The compiler is responsible for emitting arrays in a
  documented stable order (tasks: topological with lexicographic tie-break; edges,
  depends_on, source_scope, fragment_refs, source_versions: sorted).
- ``plan_hash`` is ``sha256:`` + hex digest of the canonical bytes of the plan with the
  ``plan_hash`` key removed.
- Two object keys that NFC-normalize to the same string are a ``CANONICAL_KEY_COLLISION``
  error (P02, F4). Rejection does not change the bytes of any object that was previously
  accepted, so ``NORMALIZATION_VERSION`` stays ``dcs-canon-v0.1``.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

from forge_dcs.errors import CANONICAL_KEY_COLLISION

NORMALIZATION_VERSION = "dcs-canon-v0.1"  # unchanged: collision *rejection* never alters accepted bytes
HASH_PREFIX = "sha256:"
_WS = re.compile(r"\s+")


class CanonicalizationError(ValueError):
    def __init__(self, message: str, code: str = "CANONICALIZATION_ERROR") -> None:
        super().__init__(message)
        self.code = code


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        raise CanonicalizationError("float values are not permitted in canonical payloads")
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise CanonicalizationError("object keys must be strings")
            nk = unicodedata.normalize("NFC", k)
            if nk in out:
                # F4: silently overwriting would hash two distinct inputs to the same bytes
                raise CanonicalizationError(
                    f"object keys {k!r} and another key normalize to the same NFC key {nk!r}", code=CANONICAL_KEY_COLLISION
                )
            out[nk] = _normalize(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    raise CanonicalizationError(f"unsupported type in canonical payload: {type(value).__name__}")


def canonical_bytes(obj: Any) -> bytes:
    normalized = _normalize(obj)
    text = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(obj: Any) -> str:
    return HASH_PREFIX + sha256_hex(canonical_bytes(obj))


def plan_hash(plan: dict[str, Any]) -> str:
    body = {k: v for k, v in plan.items() if k != "plan_hash"}
    return digest(body)


def normalize_prompt(text: str) -> str:
    """NFC + casefold + whitespace collapse; the only prompt view the rule engine sees."""
    t = unicodedata.normalize("NFC", text)
    t = t.casefold()
    t = _WS.sub(" ", t).strip()
    return t


def prompt_tokens(normalized: str) -> list[str]:
    return [tok for tok in re.split(r"[^\w]+", normalized) if tok]
