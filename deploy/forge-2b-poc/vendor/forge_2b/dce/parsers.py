"""Structural parsers for AttachmentMap v1 (DCE-02). Pure Python, data only — nothing here evaluates, imports or
instantiates anything from attachment content.

Every parser takes the *rendered* text of one file (as produced by ``zipingest``) and returns ``Seg`` records with
character offsets into that text. A final gap-fill pass guarantees every non-blank line belongs to at least one
segment, so any ``path:line`` citation maps back to a segment (source-map round trip).

Parsers:
  markdown  headings (with ancestry), list items, paragraphs, tables, fenced code blocks
  json      position-aware recursive descent → one segment per scalar leaf with its JSON pointer
  yaml      indentation-based *subset* (scalar keys, nested mappings, sequences, block scalars); tags are kept as
            text and never resolved — this is the "safe parser": it cannot construct objects by design
  csv       header + typed rows; records with embedded newlines stay whole (line span covers the record)
  python    ``ast.parse`` only (no compile/exec): module constants, functions, classes, imports
  html      title / headings / paragraphs / list items by tag (rendered html_text falls back to text)
  js/ts     regex: imports/requires and top-level symbols (Tree-sitter optional, not bundled)
  text      paragraphs; ``key: value`` / ``key = value`` files get key segments
"""
from __future__ import annotations

import ast
import csv
import io
import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any

MAX_SEGMENTS_PER_FILE = 5000


@dataclass
class Seg:
    kind: str                 # heading|paragraph|list_item|table_header|table_row|code_block|key|item|header|row|symbol|import|docstring|element|block|line
    start: int                # char offset into rendered text (inclusive)
    end: int                  # char offset (exclusive)
    context: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    malformed: bool = False


# --- shared helpers -------------------------------------------------------------------------------------------
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def line_starts(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def line_of(starts: list[int], offset: int) -> int:
    """1-based line number of a character offset."""
    return bisect_right(starts, offset)


def aliases_for(name: str, *, limit: int = 16) -> list[str]:
    """Unicode-aware normalized name variants: lowercase NFKC, split on _ - . / and camelCase, joined forms."""
    if not name:
        return []
    out: list[str] = []
    norm = unicodedata.normalize("NFKC", name).strip()
    low = norm.lower()
    parts = [p for p in re.split(r"[\s_\-./:]+", _CAMEL_RE.sub(" ", norm)) if p]
    cands = [low, low.replace("_", " ").replace("-", " ")] + [p.lower() for p in parts]
    if len(parts) > 1:
        cands += [" ".join(p.lower() for p in parts), "".join(p.lower() for p in parts), "_".join(p.lower() for p in parts)]
    for c in cands:
        c = c.strip()
        if c and c not in out:
            out.append(c)
        if len(out) >= limit:
            break
    return out


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(unicodedata.normalize("NFKC", text))]


def _lines(text: str) -> list[tuple[int, int, str]]:
    """(start, end_exclusive_without_newline, content) per line; the final line is included even without a newline."""
    out = []
    pos = 0
    for raw in text.split("\n"):
        out.append((pos, pos + len(raw), raw))
        pos += len(raw) + 1
    if text.endswith("\n") and out and out[-1][2] == "":
        out.pop()
    return out


def fill_gaps(text: str, segs: list[Seg]) -> list[Seg]:
    """Add ``block`` segments for runs of non-blank lines not covered by any segment; return sorted by start."""
    covered = [False] * (len(text) + 1)
    for s in segs:
        for i in range(max(0, s.start), min(len(text), s.end)):
            covered[i] = True
    out = list(segs)
    run: list[tuple[int, int]] = []

    def flush() -> None:
        if run:
            out.append(Seg("block", run[0][0], run[-1][1], {"filled_gap": True}))
            run.clear()

    for start, end, content in _lines(text):
        if not content.strip():
            flush()
            continue
        if any(covered[i] for i in range(start, end)) or start == end:
            flush()
            continue
        run.append((start, end))
    flush()
    out.sort(key=lambda s: (s.start, s.end, s.kind))
    return out[:MAX_SEGMENTS_PER_FILE]


def _fallback_lines(text: str, error: str) -> list[Seg]:
    segs = [Seg("line", s, e, {"error": error}, malformed=True) for s, e, c in _lines(text) if c.strip()]
    return segs[:MAX_SEGMENTS_PER_FILE]


# --- markdown -------------------------------------------------------------------------------------------------
_H_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LI_RE = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*([\w+-]*)")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def parse_markdown(text: str) -> list[Seg]:
    segs: list[Seg] = []
    stack: list[tuple[int, str]] = []
    lines = _lines(text)
    i = 0
    para: list[tuple[int, int]] = []

    def ancestry() -> list[str]:
        return [t for _, t in stack]

    def flush_para() -> None:
        if para:
            segs.append(Seg("paragraph", para[0][0], para[-1][1], {"heading_ancestry": ancestry()}))
            para.clear()

    while i < len(lines):
        start, end, content = lines[i]
        fm = _FENCE_RE.match(content)
        if fm:
            flush_para()
            fence = fm.group(1)[0] * 3
            j = i + 1
            while j < len(lines) and not lines[j][2].strip().startswith(fence):
                j += 1
            stop = lines[j][1] if j < len(lines) else lines[-1][1]
            segs.append(Seg("code_block", start, stop, {"heading_ancestry": ancestry(), "language": fm.group(2) or ""}))
            i = j + 1
            continue
        hm = _H_RE.match(content)
        if hm:
            flush_para()
            level, title = len(hm.group(1)), hm.group(2)
            while stack and stack[-1][0] >= level:
                stack.pop()
            segs.append(Seg("heading", start, end, {"level": level, "title": title, "heading_ancestry": ancestry()}, aliases_for(title)))
            stack.append((level, title))
            i += 1
            continue
        if content.lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1][2]):
            flush_para()
            headers = [c.strip() for c in content.strip().strip("|").split("|")]
            segs.append(Seg("table_header", start, end, {"heading_ancestry": ancestry(), "columns": headers}, [a for h in headers for a in aliases_for(h)[:2]]))
            j = i + 2
            row_n = 0
            while j < len(lines) and lines[j][2].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[j][2].strip().strip("|").split("|")]
                row_n += 1
                segs.append(Seg("table_row", lines[j][0], lines[j][1], {"heading_ancestry": ancestry(), "columns": headers, "row_index": row_n,
                                                                       "cells": dict(zip(headers, cells))}))
                j += 1
            i = j
            continue
        lm = _LI_RE.match(content)
        if lm:
            flush_para()
            segs.append(Seg("list_item", start, end, {"heading_ancestry": ancestry(), "indent": len(lm.group(1))}))
            i += 1
            continue
        if not content.strip():
            flush_para()
            i += 1
            continue
        para.append((start, end))
        i += 1
    flush_para()
    return segs


# --- json (position aware) ------------------------------------------------------------------------------------
class _JsonError(ValueError):
    pass


class _JsonPos:
    _WS = " \t\n\r"

    def __init__(self, text: str):
        self.t = text
        self.segs: list[Seg] = []

    def ws(self, i: int) -> int:
        while i < len(self.t) and self.t[i] in self._WS:
            i += 1
        return i

    def string(self, i: int) -> tuple[str, int]:
        if self.t[i] != '"':
            raise _JsonError(f"expected string at {i}")
        j = i + 1
        buf = []
        while j < len(self.t):
            c = self.t[j]
            if c == "\\":
                if j + 1 >= len(self.t):
                    break
                nxt = self.t[j + 1]
                if nxt == "u":
                    buf.append(chr(int(self.t[j + 2:j + 6], 16)))
                    j += 6
                    continue
                buf.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(nxt, nxt))
                j += 2
                continue
            if c == '"':
                return "".join(buf), j + 1
            buf.append(c)
            j += 1
        raise _JsonError(f"unterminated string at {i}")

    def value(self, i: int, pointer: str, parents: list[str], key: str | None, key_start: int | None) -> int:
        i = self.ws(i)
        if i >= len(self.t):
            raise _JsonError("unexpected end")
        c = self.t[i]
        if c == "{":
            self.segs.append(Seg("key", key_start if key_start is not None else i, i + 1,
                                 {"pointer": pointer, "parent_keys": parents, "key": key, "value_type": "object"}, aliases_for(key or "")))
            i = self.ws(i + 1)
            if self.t[i] == "}":
                return i + 1
            while True:
                i = self.ws(i)
                ks = i
                k, i = self.string(i)
                i = self.ws(i)
                if self.t[i] != ":":
                    raise _JsonError(f"expected ':' at {i}")
                i = self.value(i + 1, pointer + "/" + k.replace("~", "~0").replace("/", "~1"), parents + [k], k, ks)
                i = self.ws(i)
                if self.t[i] == ",":
                    i += 1
                    continue
                if self.t[i] == "}":
                    return i + 1
                raise _JsonError(f"expected ',' or '}}' at {i}")
        if c == "[":
            self.segs.append(Seg("key", key_start if key_start is not None else i, i + 1,
                                 {"pointer": pointer, "parent_keys": parents, "key": key, "value_type": "array"}, aliases_for(key or "")))
            i = self.ws(i + 1)
            if self.t[i] == "]":
                return i + 1
            n = 0
            while True:
                i = self.value(i, f"{pointer}/{n}", parents + [str(n)], None, None)
                n += 1
                i = self.ws(i)
                if self.t[i] == ",":
                    i += 1
                    continue
                if self.t[i] == "]":
                    return i + 1
                raise _JsonError(f"expected ',' or ']' at {i}")
        start = i
        if c == '"':
            val, i = self.string(i)
            vt = "string"
        else:
            m = re.compile(r"-?\d+(\.\d+)?([eE][+-]?\d+)?|true|false|null").match(self.t, i)
            if not m:
                raise _JsonError(f"unexpected token at {i}")
            raw = m.group(0)
            i = m.end()
            val = raw
            vt = "null" if raw == "null" else "boolean" if raw in ("true", "false") else "number"
        self.segs.append(Seg("key", key_start if key_start is not None else start, i,
                             {"pointer": pointer, "parent_keys": parents, "key": key, "value": val, "value_type": vt}, aliases_for(key or "")))
        return i


def parse_json(text: str) -> list[Seg]:
    p = _JsonPos(text)
    try:
        end = p.value(0, "", [], None, None)
        if p.ws(end) != len(text):
            raise _JsonError(f"trailing data at {end}")
    except (_JsonError, IndexError, ValueError) as ex:
        return _fallback_lines(text, f"json: {ex}")
    return p.segs


# --- yaml subset (safe by construction) ------------------------------------------------------------------------
_YAML_KV_RE = re.compile(r"^(?P<key>[^\s#'\"\[\]{}][^:#]*?|'[^']*'|\"[^\"]*\")\s*:(?:\s+(?P<val>.*))?$")
_YAML_ITEM_RE = re.compile(r"^-(?:\s+(?P<val>.*))?$")


def _yaml_scalar_type(v: str) -> str:
    v = v.strip()
    if v == "" or v in ("~", "null", "Null", "NULL"):
        return "null"
    if v in ("true", "false", "True", "False", "yes", "no", "on", "off"):
        return "boolean"
    if re.fullmatch(r"[-+]?\d+", v):
        return "integer"
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", v):
        return "float"
    if v.startswith(("[", "{")):
        return "flow"
    return "string"


def _strip_yaml_comment(v: str) -> str:
    if v.startswith(("'", '"')):
        q = v[0]
        j = v.find(q, 1)
        return v[1:j] if j > 0 else v
    return v.split(" #", 1)[0].rstrip()


def parse_yaml_subset(text: str) -> list[Seg]:
    segs: list[Seg] = []
    lines = _lines(text)
    stack: list[tuple[int, str]] = []   # (indent, key)
    i = 0
    seq_counters: dict[int, int] = {}
    while i < len(lines):
        start, end, content = lines[i]
        stripped = content.strip()
        if not stripped or stripped.startswith("#") or stripped in ("---", "..."):
            i += 1
            continue
        if "\t" in content[: len(content) - len(content.lstrip())]:
            segs.append(Seg("line", start, end, {"error": "yaml: tab indentation"}, malformed=True))
            i += 1
            continue
        indent = len(content) - len(content.lstrip(" "))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parents = [k for _, k in stack]
        body = content.strip()
        im = _YAML_ITEM_RE.match(body)
        if im:
            idx = seq_counters.get(indent, 0)
            seq_counters[indent] = idx + 1
            val = im.group("val") or ""
            kv = _YAML_KV_RE.match(val) if val else None
            if kv:   # "- key: value" → mapping inside a sequence
                stack.append((indent, f"[{idx}]"))
                body = val
                indent = indent + 2
                parents = parents + [f"[{idx}]"]
            else:
                v = _strip_yaml_comment(val)
                segs.append(Seg("item", start, end, {"parent_keys": parents, "index": idx, "path": ".".join(parents + [f"[{idx}]"]),
                                                     "value": v, "value_type": _yaml_scalar_type(v), "tag": _yaml_tag(val)}))
                i += 1
                continue
        else:
            for k in [k for k in seq_counters if k >= indent]:   # a new key closes every deeper/sibling sequence
                seq_counters.pop(k)
        kv = _YAML_KV_RE.match(body)
        if not kv:
            segs.append(Seg("line", start, end, {"error": "yaml: not key/value", "parent_keys": parents}, malformed=True))
            i += 1
            continue
        key = kv.group("key").strip().strip("'\"")
        raw_val = (kv.group("val") or "").strip()
        path = ".".join(parents + [key])
        ctx: dict[str, Any] = {"key": key, "path": path, "parent_keys": parents, "tag": _yaml_tag(raw_val)}
        if raw_val in ("|", ">", "|-", ">-", "|+", ">+") or raw_val.startswith(("|", ">")) and raw_val[1:].strip("+-0123456789") == "":
            j = i + 1
            while j < len(lines) and (not lines[j][2].strip() or len(lines[j][2]) - len(lines[j][2].lstrip(" ")) > indent):
                j += 1
            last = j - 1
            while last > i and not lines[last][2].strip():
                last -= 1
            ctx.update(value_type="block_scalar", compound=True, lines=last - i + 1)
            segs.append(Seg("key", start, lines[last][1], ctx, aliases_for(key)))
            i = j
            continue
        if raw_val.startswith(("[", "{")) and raw_val.count("[") + raw_val.count("{") > raw_val.count("]") + raw_val.count("}"):
            j = i
            depth = 0
            while j < len(lines):
                depth += lines[j][2].count("[") + lines[j][2].count("{") - lines[j][2].count("]") - lines[j][2].count("}")
                if depth <= 0:
                    break
                j += 1
            j = min(j, len(lines) - 1)
            ctx.update(value_type="flow", compound=True, lines=j - i + 1)
            segs.append(Seg("key", start, lines[j][1], ctx, aliases_for(key)))
            i = j + 1
            continue
        if raw_val == "" or raw_val.startswith("#"):
            nxt = next((l for l in lines[i + 1:] if l[2].strip() and not l[2].strip().startswith("#")), None)
            is_seq = bool(nxt and nxt[2].strip().startswith("-") and len(nxt[2]) - len(nxt[2].lstrip(" ")) >= indent)
            is_map = bool(nxt and len(nxt[2]) - len(nxt[2].lstrip(" ")) > indent)
            ctx.update(value_type="sequence" if is_seq else "mapping" if is_map else "null", compound=is_seq or is_map)
            segs.append(Seg("key", start, end, ctx, aliases_for(key)))
            stack.append((indent, key))
            i += 1
            continue
        v = _strip_yaml_comment(raw_val)
        ctx.update(value=v, value_type=_yaml_scalar_type(v))
        segs.append(Seg("key", start, end, ctx, aliases_for(key)))
        i += 1
    return segs


def _yaml_tag(v: str) -> str:
    m = re.match(r"(![\w!/:.-]*)", v.strip())
    return m.group(1) if m else ""


# --- csv -------------------------------------------------------------------------------------------------------
def _cell_type(v: str) -> str:
    s = v.strip()
    if s == "":
        return "empty"
    if re.fullmatch(r"[-+]?\d+", s):
        return "integer"
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", s):
        return "float"
    if s.lower() in ("true", "false", "yes", "no"):
        return "boolean"
    return "string"


def parse_csv(text: str, *, delimiter: str = ",") -> list[Seg]:
    starts = line_starts(text)
    n_lines = len(_lines(text))

    def span(l1: int, l2: int) -> tuple[int, int]:
        s = starts[l1 - 1] if l1 - 1 < len(starts) else len(text)
        e = starts[l2] - 1 if l2 < len(starts) else len(text)
        return s, max(s, e)

    segs: list[Seg] = []
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    prev_end = 0
    headers: list[str] | None = None
    row_idx = 0
    col_types: dict[str, dict[str, int]] = {}
    try:
        for row in reader:
            l1, l2 = prev_end + 1, reader.line_num
            prev_end = l2
            if l2 > n_lines:
                l2 = n_lines
            if not row or all(c.strip() == "" for c in row):
                continue
            s, e = span(l1, l2)
            if headers is None:
                headers = [h.strip() for h in row]
                segs.append(Seg("header", s, e, {"columns": headers}, [a for h in headers for a in aliases_for(h)[:3]]))
                col_types = {h: {} for h in headers}
                continue
            row_idx += 1
            cells = dict(zip(headers, row))
            types = {h: _cell_type(v) for h, v in cells.items()}
            for h, t in types.items():
                col_types[h][t] = col_types[h].get(t, 0) + 1
            segs.append(Seg("row", s, e, {"columns": headers, "row_index": row_idx, "cells": cells, "types": types,
                                          "ragged": len(row) != len(headers), "multiline": l2 > l1}))
    except csv.Error as ex:
        return _fallback_lines(text, f"csv: {ex}")
    if headers is not None:
        summary = {h: max(sorted(t), key=lambda k: t[k]) if t else "empty" for h, t in col_types.items()}
        segs[0].context["column_types"] = summary
        segs[0].context["rows"] = row_idx
    return segs


# --- python (ast only) -----------------------------------------------------------------------------------------
def _col_to_offset(line_text: str, byte_col: int) -> int:
    return len(line_text.encode("utf-8")[:byte_col].decode("utf-8", "replace"))


def parse_python(text: str) -> list[Seg]:
    try:
        tree = ast.parse(text)   # parse only; never compile/exec
    except (SyntaxError, ValueError, RecursionError) as ex:
        return _fallback_lines(text, f"python: {type(ex).__name__}: {getattr(ex, 'msg', ex)}")
    lines = _lines(text)
    starts = line_starts(text)

    def off(lineno: int, col: int) -> int:
        return starts[lineno - 1] + _col_to_offset(lines[lineno - 1][2], col)

    segs: list[Seg] = []
    doc = ast.get_docstring(tree, clean=False)
    if doc and tree.body and isinstance(tree.body[0], ast.Expr):
        n = tree.body[0]
        segs.append(Seg("docstring", off(n.lineno, n.col_offset), off(n.end_lineno, n.end_col_offset), {"symbol": "<module>", "text_plain": doc.strip().splitlines()[0] if doc.strip() else ""}))

    def visit(node: ast.AST, qual: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = ".".join(qual + [child.name])
                kind = "class" if isinstance(child, ast.ClassDef) else "function"
                d = ast.get_docstring(child, clean=False)
                segs.append(Seg("symbol", off(child.lineno, child.col_offset), off(child.end_lineno, child.end_col_offset),
                                {"symbol": name, "symbol_kind": kind, "parent_keys": qual, "docstring": (d or "").strip().splitlines()[0] if d else ""},
                                aliases_for(child.name)))
                visit(child, qual + [child.name])
            elif isinstance(child, (ast.Assign, ast.AnnAssign)) and not qual:
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                names = [t.id for t in targets if isinstance(t, ast.Name)]
                if not names:
                    continue
                val = child.value
                ctx: dict[str, Any] = {"symbol": names[0], "symbol_kind": "constant", "parent_keys": [], "names": names}
                if isinstance(val, ast.Constant):
                    ctx["value"] = repr(val.value) if not isinstance(val.value, str) else val.value
                    ctx["value_type"] = type(val.value).__name__
                segs.append(Seg("symbol", off(child.lineno, child.col_offset), off(child.end_lineno, child.end_col_offset), ctx,
                                [a for n in names for a in aliases_for(n)]))
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                if isinstance(child, ast.Import):
                    mods = [a.name for a in child.names]
                else:
                    mods = [("." * (child.level or 0)) + (child.module or "")]
                segs.append(Seg("import", off(child.lineno, child.col_offset), off(child.end_lineno, child.end_col_offset),
                                {"modules": mods, "names": [a.name for a in child.names], "parent_keys": qual}))

    visit(tree, [])
    return segs


# --- html ------------------------------------------------------------------------------------------------------
_HTML_EL_RE = re.compile(r"<(title|h[1-6]|p|li|td|th)\b[^>]*>(.*?)</\1\s*>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_html(text: str) -> list[Seg]:
    segs: list[Seg] = []
    for m in _HTML_EL_RE.finditer(text):
        tag = m.group(1).lower()
        plain = _TAG_RE.sub("", m.group(2)).strip()
        segs.append(Seg("element", m.start(), m.end(), {"tag": tag, "text_plain": plain}, aliases_for(plain) if tag in ("title", "h1", "h2", "h3") else []))
    return segs


# --- js / ts (regex; Tree-sitter optional, not bundled) ----------------------------------------------------------
_JS_IMPORT_RE = re.compile(r"^\s*(?:import\b[^;\n]*?\bfrom\s*['\"]([^'\"]+)['\"]|(?:const|let|var)\s+[\w{},\s]+=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\))", re.MULTILINE)
_JS_SYMBOL_RE = re.compile(r"^(?:export\s+(?:default\s+)?)?(?:(?:async\s+)?function\s*\*?\s*(\w+)|class\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=)", re.MULTILINE)


def parse_js(text: str) -> list[Seg]:
    segs: list[Seg] = []
    for m in _JS_IMPORT_RE.finditer(text):
        segs.append(Seg("import", m.start(), m.end(), {"modules": [m.group(1) or m.group(2)], "names": []}))
    for m in _JS_SYMBOL_RE.finditer(text):
        name = m.group(1) or m.group(2) or m.group(3)
        kind = "class" if m.group(2) else "function" if m.group(1) else "constant"
        segs.append(Seg("symbol", m.start(), m.end(), {"symbol": name, "symbol_kind": kind, "parent_keys": []}, aliases_for(name)))
    return segs


# --- plain text -------------------------------------------------------------------------------------------------
_KV_LINE_RE = re.compile(r"^\s*[\w.\-]+\s*[:=]\s*\S")


def parse_text(text: str) -> list[Seg]:
    lines = [l for l in _lines(text) if l[2].strip()]
    if lines and sum(1 for l in lines if _KV_LINE_RE.match(l[2]) or l[2].strip().startswith(("#", "[", ";"))) >= max(1, int(0.8 * len(lines))):
        if any("=" in l[2] and ":" not in l[2].split("=", 1)[0] for l in lines if _KV_LINE_RE.match(l[2])):
            return _parse_ini(text)
        return parse_yaml_subset(text)
    segs: list[Seg] = []
    para: list[tuple[int, int]] = []
    for s, e, c in _lines(text):
        if c.strip():
            para.append((s, e))
        elif para:
            segs.append(Seg("paragraph", para[0][0], para[-1][1]))
            para = []
    if para:
        segs.append(Seg("paragraph", para[0][0], para[-1][1]))
    return segs


_INI_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_INI_KV_RE = re.compile(r"^\s*([\w.\-]+)\s*=\s*(.*)$")


def _parse_ini(text: str) -> list[Seg]:
    segs: list[Seg] = []
    section = ""
    for s, e, c in _lines(text):
        if not c.strip() or c.strip().startswith(("#", ";")):
            continue
        sm = _INI_SECTION_RE.match(c)
        if sm:
            section = sm.group(1).strip()
            segs.append(Seg("key", s, e, {"key": section, "path": section, "parent_keys": [], "value_type": "mapping", "compound": True}, aliases_for(section)))
            continue
        km = _INI_KV_RE.match(c)
        if km:
            k, v = km.group(1), _strip_yaml_comment(km.group(2).strip())
            parents = [section] if section else []
            segs.append(Seg("key", s, e, {"key": k, "path": ".".join(parents + [k]), "parent_keys": parents, "value": v, "value_type": _yaml_scalar_type(v)}, aliases_for(k)))
        else:
            segs.append(Seg("line", s, e, {"error": "ini: not key=value"}, malformed=True))
    return segs


# --- dispatch ---------------------------------------------------------------------------------------------------
LANGUAGE_BY_EXT = {".md": "markdown", ".rst": "markdown", ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".csv": "csv", ".tsv": "tsv",
                   ".py": "python", ".html": "html", ".htm": "html", ".js": "javascript", ".ts": "typescript", ".toml": "toml", ".ini": "ini",
                   ".cfg": "ini", ".env.example": "ini", ".txt": "text", ".log": "text", ".sql": "sql", ".sh": "shell", ".xml": "xml"}


def language_for(path: str, rendered: str) -> str:
    base = path.rsplit("/", 1)[-1]
    low = base.lower()
    if low.endswith(".env.example"):
        return "ini"
    ext = "." + low.rsplit(".", 1)[-1] if "." in low else ""
    if ext in LANGUAGE_BY_EXT:
        lang = LANGUAGE_BY_EXT[ext]
        return "text" if lang == "html" and rendered == "html_text" else lang
    if base in ("README", "CHANGELOG", "LICENSE", "NOTICE"):
        return "markdown"
    if base in ("Dockerfile", "Makefile"):
        return "shell"
    return "text"


def parse_file(text: str, language: str) -> list[Seg]:
    if language == "markdown":
        segs = parse_markdown(text)
    elif language == "json":
        segs = parse_json(text)
    elif language == "yaml":
        segs = parse_yaml_subset(text)
    elif language == "csv":
        segs = parse_csv(text)
    elif language == "tsv":
        segs = parse_csv(text, delimiter="\t")
    elif language == "python":
        segs = parse_python(text)
    elif language == "html":
        segs = parse_html(text)
    elif language in ("javascript", "typescript"):
        segs = parse_js(text)
    elif language in ("ini", "toml"):
        segs = _parse_ini(text) if "=" in text else parse_yaml_subset(text)
    else:
        segs = parse_text(text)
    return fill_gaps(text, segs)
