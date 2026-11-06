"""Text rendering for the DCE ``on`` lane: the D0 answers read from the attachment map (manifest, folder inventory,
structure, typed operators) and the final run markdown with the coverage gate.

Everything here is string assembly over already-decided facts — no retrieval, no model, no I/O. The D0 renderers
mutate the executor's ``NodeResult`` (answer, detail, spans) so that the executor stays a dispatcher.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from .. import zipingest

if TYPE_CHECKING:  # pragma: no cover
    from .shadow import NodeResult, Plan


def _span(plan: Plan, path: str, line: int, seg_id: str) -> dict[str, Any]:
    """A cited span with the first line of its map-resolved text (raises when the pointer does not round-trip → node FAILED)."""
    loc = plan.amap.resolve(seg_id, plan.scope)
    return {"path": path, "line": line, "text": loc["text"].split("\n")[0][:200], "seg_id": seg_id}


# --- manifest / structure ---------------------------------------------------------------------------------------------------------
def manifest(ings: list[zipingest.Ingest]) -> str:
    return "".join(zipingest.render_manifest_markdown(i) for i in ings)


_FOLDER_MENTION_RE = re.compile(r"(?:in|inside|under|within|of|does)\s+(?:the\s+)?`?([\w./-]+?)`?\s+(?:folder|directory|dir|subfolder)\b", re.I)


def folder_inventory(ings: list[zipingest.Ingest], question: str) -> tuple[str, str] | None:
    """D0 answer for a folder question ("What is in the PUBLIC folder?"): the manifest rows under that folder, resolved
    case-insensitively against the directory components of the archive paths. Returns (method, markdown) or None when
    the question names no folder; a folder that is not in the archive gets the honest list of folders that are."""
    m = _FOLDER_MENTION_RE.search(question)
    if not m:
        return None
    want = m.group(1).strip("/").casefold()
    dirs: dict[str, str] = {}   # casefolded dir path -> as written
    for ing in ings:
        for e in ing.entries:
            parts = e.path.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                d = "/".join(parts[:i])
                dirs.setdefault(d.casefold(), d)
    match = dirs.get(want) or next((d for k, d in dirs.items() if k.endswith("/" + want) or k.split("/")[-1] == want), None)
    if match is None:
        top = sorted({d for d in dirs.values() if "/" not in d})
        return "manifest_folder", (f"**Not found in the attached archive(s)** — no folder named `{m.group(1)}`. Top-level folders: "
                                   + (", ".join(f"`{d}/`" for d in top) if top else "none (all files are at the archive root)") + ".")
    rows = ["| # | path | status | bytes | lines | type | note |", "|---|---|---|---|---|---|---|"]
    n = 0
    for ing in ings:
        for e in ing.entries:
            if e.path == match or e.path.startswith(match + "/"):
                n += 1
                rows.append(f"| {n} | `{e.path}` | {e.status} | {e.bytes} | {e.lines or ''} | {e.mime} | {e.skip_reason or ing.integrity.get(e.path, '')} |")
    sub = sorted({d for d in dirs.values() if d.startswith(match + "/") and d.count("/") == match.count("/") + 1})
    head = f"**Folder** `{match}/` · {n} file(s)" + (f" · subfolders: " + ", ".join(f"`{d.split('/')[-1]}/`" for d in sub) if sub else "") + "\n\n"
    return "manifest_folder", head + "\n".join(rows) + "\n"


def structure(plan: Plan) -> str:
    rows = []
    for f in plan.amap.files:
        if f.status != "INCLUDED":
            continue
        segs = plan.amap.segments_for(f.file_id)
        kinds: dict[str, int] = {}
        for s in segs:
            kinds[s.kind] = kinds.get(s.kind, 0) + 1
        rows.append(f"| `{f.path}` | {f.language} | {'/'.join(f.role_hints) or '—'} | {f.lines} | " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) + " |")
    return "| file | language | role | lines | segments |\n|---|---|---|---|---|\n" + "\n".join(rows) + "\n"


def anchor_of(entry: dict[str, Any]) -> str:
    cov = entry.get("coverage") or {}
    missing = cov.get("missing") or cov.get("anchors_missing") or []
    return ", ".join(f"'{m}'" for m in missing[:3]) if isinstance(missing, list) and missing else "the requested literal"


def readable_files(plan: Plan) -> int:
    return sum(1 for f in plan.amap.files if f.status == "INCLUDED")


# --- typed D0 operators -------------------------------------------------------------------------------------------------------------
def typed_count(r: NodeResult, tc: dict[str, Any], plan: Plan) -> None:
    r.method = tc["method"]
    if tc["method"].startswith("manifest_count"):
        r.answer = (f"**{tc['value']}** {tc['method'].split(':')[1]} in the attached archive(s)" + (f" — {tc['detail']}" if tc.get("detail") else "")
                    + " (counted from the archive manifest; no file content was read and no model was called).")
    else:
        r.answer = f"**{tc['value']}** ({tc['method'].replace(':', ': ')}) in `{tc['path']}`"
    for seg_id, line in zip(tc["spans"], tc["lines"]):
        loc = plan.amap.resolve(seg_id, plan.scope)
        r.spans.append({"path": loc["path"], "line": line, "text": loc["text"].split("\n")[0][:200], "seg_id": seg_id})


def typed_compare(r: NodeResult, td: dict[str, Any], plan: Plan) -> None:
    r.method = td["method"]
    lines = [f"- `{d['key']}`: " + " vs ".join(f"`{s['value']}` (`{s['path']}:{s['line']}`)" for s in d["sides"]) for d in td["differs"]]
    only = [f"- `{k}` only in `{p}`" for p, ks in td["only_in"].items() for k in ks]
    r.answer = (f"Verdict: **{td['verdict']}** — {len(td['differs'])} differing key(s), {len(td['same'])} identical.\n" + "\n".join(lines + only)).strip()
    for d in td["differs"]:
        for s in d["sides"]:
            r.spans.append(_span(plan, s["path"], s["line"], s["seg_id"]))


def typed_dated_sections(r: NodeResult, ts: dict[str, Any], plan: Plan) -> None:
    # D0: dated/versioned headings ordered from the map; the selector picks the entry, its body lines come along
    r.method = ts["method"]
    picked = [ts["entries"][i] for i in ts["chosen"]] if ts["chosen"] else ts["entries"]
    if ts["chosen"]:
        parts = []
        for en in picked:
            parts.append(f"**{en['text'].lstrip('# ').strip()}** (`{ts['path']}:{en['line']}`, {ts['ordered_by']} {en['key']})"
                         + "".join(f"\n  {b['text'].strip()} (`{ts['path']}:{b['line']}`)" for b in en["body"]))
        r.answer = "\n".join(parts) + (f"\n_{ts['note']}_" if ts["note"] else "")
    else:
        r.answer = (f"{len(ts['entries'])} dated entries in `{ts['path']}` ({ts['ordered_by']} order, newest first) — {ts['note']}:\n"
                    + "\n".join(f"- {en['text'].lstrip('# ').strip()} (`{ts['path']}:{en['line']}`)" for en in ts["entries"]))
        r.detail = ts["note"]
    for en in picked:
        for sp in [en] + (en["body"] if ts["chosen"] else []):
            r.spans.append(_span(plan, ts["path"], sp["line"], sp["seg_id"]))


def typed_table(r: NodeResult, tt: dict[str, Any], plan: Plan) -> None:
    # D0 (Phase 2): a table row, a column extreme, a filtered column, a commit range or a patch rollup read from the map — no model call
    r.method = tt["method"]
    if tt["method"] == "typed_file_which":
        # the files that belong to every file group the question named, read from the manifest
        groups = " ∩ ".join(f"`{g}`" for g in tt["groups"])
        r.answer = (f"**{len(tt['entries'])} file(s)** in the archive match {groups}:\n"
                    + "\n".join(f"- `{en['path']}` ({en['segments']} indexed segment(s))" for en in tt["entries"]))
        for en in tt["entries"]:
            r.spans.append(_span(plan, en["path"], en["line"], en["seg_id"]))
        return
    if tt["method"] == "typed_table_row":
        parts = []
        for en in tt["entries"]:
            cells = "; ".join(f"{c['column']}: **{c['value']}**" for c in en["cells"]) or "(no cells)"
            parts.append(f"- **{en['label']}** — {cells} (`{en['path']}:{en['line']}`)")
        r.answer = "\n".join(parts) + (f"\n_{tt['note']}_" if tt["note"] else "")
        r.detail = tt["note"]
        for en in tt["entries"]:
            r.spans.append(_span(plan, en["path"], en["line"], en["seg_id"]))
    elif tt["method"] == "typed_table_extreme":
        col = tt["column"] + (f" → {tt['sub']}" if tt.get("sub") else "")
        others = ", ".join(f"{o['label']} {o['value']:g}" for o in tt["others"])
        r.answer = (f"**{tt['label']}** — {tt['extreme']} `{col}`: **{tt['cell']}** (`{tt['path']}:{tt['line']}`; {tt['rows_considered']} rows compared"
                    + (f", next: {others}" if others else "") + ")")
        r.spans.append(_span(plan, tt["path"], tt["line"], tt["seg_id"]))
    elif tt["method"] == "typed_table_filter":
        blocks = []
        for tb in tt["tables"]:
            where = f" under *{tb['heading']}*" if tb.get("heading") else ""
            lines = [f"- **{en['label']}** — `{tb['column']}`: {en['cell']}" + ("; " + "; ".join(f"{c['column']}: {c['value']}" for c in en["cells"]) if en["cells"] else "")
                     + f" (`{tb['path']}:{en['line']}`)" for en in tb["entries"]]
            blocks.append(f"**{len(tb['entries'])} of {tb['rows_considered']} row(s)** with a {tt['want']} `{tb['column']}` in `{tb['path']}`{where}:\n" + "\n".join(lines))
            for en in tb["entries"]:
                r.spans.append(_span(plan, tb["path"], en["line"], en["seg_id"]))
        r.answer = "\n\n".join(blocks) + " \n_(read from the table, no model called)_" + (f"\n_{tt['note']}_" if tt["note"] else "")
        r.detail = tt["note"]
    elif tt["method"] == "typed_commit_range":
        lines = [f"- `{c['sha']}` {c['subject']} (`{tt['path']}:{c['line']}`)" for c in tt["commits"]]
        r.answer = (f"**{len(tt['commits'])} commit(s)** after `{tt['older']}` up to `{tt['newer']}` in `{tt['path']}` ({tt['log_lines']} log lines read, no model called):\n"
                    + "\n".join(lines))
        for c in tt["commits"]:
            r.spans.append({"path": tt["path"], "line": c["line"], "text": f"{c['sha']} {c['subject']}"[:200], "seg_id": c["seg_id"]})
    else:   # typed_diff_rollup
        lines = [f"- `{x['path']}` — {x['status']}, +{x['added']} −{x['removed']} in {x['hunks']} hunk(s) (`{x['patch']}:{x['line']}`)" for x in tt["files"]]
        r.answer = (f"**{len(tt['files'])} file(s)** changed in `{'`, `'.join(tt['patches'])}` (+{tt['added']} −{tt['removed']}; read from the patch headers, no model called):\n"
                    + "\n".join(lines))
        for x in tt["files"]:
            r.spans.append(_span(plan, x["patch"], x["line"], x["seg_id"]))


def typed_verdict(r: NodeResult, tv: dict[str, Any], plan: Plan) -> None:
    # D0: the labelled verdict / decision / status line(s) read from the map — no model call
    r.method = tv["method"]
    lines = [f"- `{en['path']}:{en['line']}` — {en['text'][:200]}" for en in tv["entries"]]
    if tv["method"] == "typed_polar_verdict":
        n = len(tv["entries"])
        r.answer = (f"**{tv['answer']}** — the stated {'/'.join(sorted({en['label'].casefold() for en in tv['entries']}))} is **{tv['value']}** "
                    f"({n} labelled line{'s' if n != 1 else ''}):\n" + "\n".join(lines) + "\n_(read from the labelled line(s), no model called)_" + (f"\n_{tv['note']}_" if tv["note"] else ""))
        r.detail = tv["note"]
    elif tv["value"] is not None:
        n = len(tv["entries"])
        r.answer = (f"**{tv['value']}** — stated on {n} labelled line{'s' if n != 1 else ''} ({', '.join(sorted({en['label'].casefold() for en in tv['entries']}))}):\n"
                    + "\n".join(lines) + "\n_(read from the labelled line(s), no model called)_")
    else:
        r.answer = ("The attached files state different values — none is chosen:\n"
                    + "\n".join(f"- `{en['path']}:{en['line']}` — **{en['value']}** — {en['text'][:160]}" for en in tv["entries"])
                    + f"\n_{tv['note']}_")
        r.detail = tv["note"]
    for en in tv["entries"]:
        r.spans.append(_span(plan, en["path"], en["line"], en["seg_id"]))


def typed_key_lookup(r: NodeResult, tk: dict[str, Any], plan: Plan) -> None:
    # D0: the best-ranked line *is* the asked config key — read the value from the map, no model call
    r.method = tk["method"]
    vals = tk["values"]
    if len(vals) == 1 and not tk["ambiguous"]:
        r.answer = f"`{tk['key']}` = **{vals[0]['value']}** (`{vals[0]['path']}:{vals[0]['line']}`)" + (f" — {tk['note']}" if tk["note"] else "")
    else:
        r.answer = (f"`{tk['key']}` has {len(vals)} values in the attached files — the question does not say which file, so none is chosen:\n"
                    + "\n".join(f"- **{v['value']}** (`{v['path']}:{v['line']}`)" for v in vals))
        r.detail = tk["note"]
    if tk.get("corroborating"):
        r.answer += "\n" + "Also stated in: " + ", ".join(f"`{c['path']}:{c['line']}`" for c in tk["corroborating"])
    for v in vals + tk.get("corroborating", []):
        r.spans.append(_span(plan, v["path"], v["line"], v["seg_id"]))


# --- the run ---------------------------------------------------------------------------------------------------------------------------
def run_markdown(run_id: str, plan: Plan, results: list[NodeResult], gate: dict[str, Any], *, backend_model: str) -> str:
    out = [f"**forge-2b DCE lane** · run `{run_id}` · mode `on` · backend `{backend_model}` · {gate['model_calls_made']} model call(s)  \n"
           "Deterministic (D0) nodes answer from the verified attachment map; D1/D2 nodes send only map-verified excerpts to the fixed model and every "
           "quote is checked verbatim. Status: **" + gate["status"] + "**.\n"]
    goal_text = {g.id: g for g in plan.ir.goals}
    wants_list = any(g.operator == "list" for g in plan.ir.goals) or not plan.ir.goals
    wants_structure = any(g.operator == "inspect" and len(g.span.text.split()) <= 4 for g in plan.ir.goals)
    for r in results:
        if r.kind == "inventory" and not r.goal_id:
            if wants_list:
                out.append("\n**Files (manifest, D0):**\n\n" + r.answer)
            continue
        if r.kind == "parse_structure" and not r.goal_id:
            if wants_structure:
                out.append("\n**Structure (attachment map, D0):**\n\n" + r.answer)
            continue
        if not r.goal_id or r.node_id != f"{r.goal_id}_{r.kind}":
            continue   # compare side-lookups are folded into their compare node
        g = goal_text.get(r.goal_id)
        label = {"COMMITTED": "✓", "PARTIAL": "◐", "FAILED": "✗", "UNSUPPORTED": "⊘", "SKIPPED": "…"}[r.status]
        out.append(f"\n### {label} {g.operator if g else r.kind}: {g.span.text if g else r.node_id}\n")
        out.append(f"_{r.route} · {r.method or r.kind} · {r.status}_" + (f" — {r.detail}" if r.detail and r.status != "COMMITTED" else "") + "\n\n")
        if r.answer:
            out.append(r.answer.rstrip() + "\n")
        if r.spans and r.method not in ("manifest", "attachment_map"):
            out.append("\n**Excerpts checked (no answer in them):**\n" if r.method == "q2_not_in_excerpts" else "\n**Evidence:**\n")
            for s in r.spans[:12]:
                txt = s.get("text") or ""
                out.append(f"- `{s['path']}:{s['line']}`" + (f" — {txt[:200]}" if txt else "") + "\n")
        if r.attempts:
            out.append(f"\n_{len(r.attempts)} model attempt(s); prompt sha `{r.attempts[-1].get('prompt_sha256', '')[:12]}`_\n")
    out.append("\n**Coverage gate:**\n\n| goal | operator | status |\n|---|---|---|\n")
    for g in gate["goals"]:
        out.append(f"| {g['text'][:80].replace('|', '\\|')} | {g['operator']} | {g['status']} |\n")
    if gate["unresolved"]:
        out.append("\nUnresolved request parts (not acted on): " + "; ".join(f"“{u['text'][:60]}” ({u['reason']})" for u in gate["unresolved"]) + "\n")
    if gate["span_problems"]:
        out.append("\nSpan verification problems: " + "; ".join(gate["span_problems"][:5]) + "\n")
    if gate["status"] != "COMMITTED":
        out.append(f"\n_Run {gate['status']}: goals not marked COMMITTED were not answered with verified evidence; nothing was guessed._\n")
    return "".join(out)


def results_trace(results: list[NodeResult]) -> list[dict[str, Any]]:
    out = []
    for r in results:
        d = asdict(r)
        d["spans"] = [f"{s['path']}:{s['line']}" for s in r.spans]
        d["answer_sha256"] = hashlib.sha256(r.answer.encode()).hexdigest()[:16]
        d.pop("answer")
        out.append(d)
    return out
