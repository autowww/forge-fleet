"""Deterministic text fragment inventory (P02). Pure function over original bytes.

Parser ``PARSER_ID`` = ``dcs.fragments.text_paragraphs.v0.1``:

- Input is the **original** byte sequence of a registered source (already validated as UTF-8).
- Offsets are **byte** offsets into those bytes, half-open ``[byte_start, byte_end)``.
- ``#root`` always exists and spans the whole document; its digest equals the content hash.
- For ``text/plain`` and ``text/markdown`` the document is split into paragraphs: maximal runs
  of non-blank lines, where lines are delimited by ``\\n`` and a line is blank when it contains
  only ASCII spaces, tabs and ``\\r``. A paragraph fragment spans from the first byte of its
  first line to the last non-``\\r`` byte of its last line (so CRLF files never leak a ``\\r``
  into a fragment and LF/CRLF variants of the same text produce the same fragment digests).
  Empty paragraphs are never emitted. IDs are ``p0001``, ``p0002``, … in document order
  (zero-padded to at least four digits; the grammar allows up to 64 chars).
- ``application/json`` yields ``#root`` only in v0.1 (structural JSON fragments are not a
  P02 deliverable).
- Splitting only ever happens at ``\\n`` (0x0A), which cannot occur inside a multi-byte UTF-8
  sequence, so every fragment is itself valid UTF-8 and Unicode boundaries are preserved.

Changing any of the rules above requires a new ``PARSER_ID``; registered inventories are
immutable and carry the parser id they were produced with.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

PARSER_ID = "dcs.fragments.text_paragraphs.v0.1"
ROOT_FRAGMENT_ID = "root"
_BLANK = frozenset(b" \t\r")


@dataclass(frozen=True)
class Fragment:
    fragment_id: str
    ordinal: int
    byte_start: int
    byte_end: int
    sha256: str  # "sha256:<hex>" of the fragment bytes

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _is_blank(line: bytes) -> bool:
    return all(b in _BLANK for b in line)


def paragraph_spans(data: bytes) -> list[tuple[int, int]]:
    """Half-open byte spans of paragraphs; deterministic, no decoding."""
    spans: list[tuple[int, int]] = []
    pos = 0
    para_start: int | None = None
    para_end = 0
    n = len(data)
    while pos <= n:
        nl = data.find(b"\n", pos)
        line_end = n if nl < 0 else nl
        line = data[pos:line_end]
        if _is_blank(line):
            if para_start is not None:
                spans.append((para_start, para_end))
                para_start = None
        else:
            if para_start is None:
                para_start = pos
            end = line_end
            while end > pos and data[end - 1] == 0x0D:  # strip trailing \r (CRLF)
                end -= 1
            para_end = end
        if nl < 0:
            break
        pos = nl + 1
    if para_start is not None:
        spans.append((para_start, para_end))
    return spans


def inventory(data: bytes, mime: str) -> list[Fragment]:
    """``#root`` first, then paragraphs in document order (text types only)."""
    out = [Fragment(ROOT_FRAGMENT_ID, 0, 0, len(data), _digest(data))]
    if mime in ("text/plain", "text/markdown"):
        for i, (s, e) in enumerate(paragraph_spans(data), start=1):
            out.append(Fragment(f"p{i:04d}", i, s, e, _digest(data[s:e])))
    return out
