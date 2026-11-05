"""Graph executor for forge-2b: DCS plan -> fragment windows -> atomic Q2 decisions -> reduce.

Node kinds (all recorded in the run trace, every model call is one *atomic* decision):

  source        (zero_model)  bytes registered in forge-dcs, fragments = DCS paragraphs
  plan          (zero_model)  forge-dcs STRICT PlanIR (plan_hash) for the extract intent
  triage        (zero_model)  deterministic boilerplate filter + signal score over paragraphs
  w####         (fixed_model) one window of consecutive kept paragraphs -> Q2 JSON decision
  reduce        (zero_model)  dedupe + rank statements, top-N
  result        (zero_model)  committed only if >= 1 window node COMMITTED

The model never sees the plan, other windows' outputs, or the ranking; it only decides
"which statements in THIS window are material", returning a validated JSON object.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from jsonschema import Draft202012Validator

CATEGORIES = [
    "REVENUE", "PROFIT", "SEGMENT", "CUSTOMER", "CAPITAL_RETURN", "CHARGE",
    "REGULATORY", "CONTRACT", "LITIGATION", "OPERATIONS", "GEOGRAPHY", "OTHER",
]
DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["statements"],
    "properties": {
        "statements": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "category", "impact"],
                "properties": {
                    "text": {"type": "string", "minLength": 12, "maxLength": 400},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "impact": {"type": "integer", "minimum": 1, "maximum": 5},
                },
            },
        }
    },
}
DECISION_VALIDATOR = Draft202012Validator(DECISION_SCHEMA)

SYSTEM_PROMPT = (
    "You are a financial analyst reading one excerpt of a company's SEC Form 10-K. "
    "Select at most 6 statements from THIS excerpt that are material and company-specific: "
    "reported revenue, gross margin, operating expenses, operating income, net income, EPS, segment or "
    "end-market revenue and operating income, customer concentration percentages, share repurchases "
    "(shares and dollars) and dividends, inventory or other charges, export controls or other regulatory "
    "restrictions, major licenses or purchase obligations, litigation, headcount, geographic revenue. "
    "Prefer statements that carry a specific reported figure; when the excerpt is a table, write one "
    "statement per material line item in the form '<line item> was <value> <unit> in <period>' using "
    "the header row for periods and units. Keep the exact figures from the excerpt. "
    "Ignore: table of contents, item headers, signatures, items incorporated by reference to a proxy "
    "statement, forward-looking-statement safe-harbor language, generic 'material adverse effect' risk "
    "boilerplate, and definitions. If nothing qualifies return an empty list. "
    'Return ONLY one JSON object: {"statements":[{"text":"...","category":"<one of '
    + "|".join(CATEGORIES)
    + '>","impact":1-5}]}. No markdown, no commentary.'
)

_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:billion|million|thousand)\b", re.I)
_PCT = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")
_KEYTERMS = re.compile(
    r"\b(revenue|gross margin|net income|operating income|diluted|per share|repurchase|dividend|"
    r"export|license|customer|charge|inventory|obligation|employees|lawsuit|class action|headcount|"
    r"data center|gaming|automotive|segment|taiwan|united states|blackwell)\b",
    re.I,
)
_BOILERPLATE = re.compile(
    r"^(item\s+\d+[a-c]?\.?|part\s+[ivx]+\b|table of contents|signatures?|exhibit index|exhibit no\.?|"
    r"united states securities and exchange commission|form 10-k|page \d+)\b|"
    r"\bincorporated (herein )?by reference\b|\bforward-looking statements?\b|\bsafe harbor\b|"
    r"\bmaterial adverse effect on our business, financial condition\b",
    re.I,
)


@dataclass
class Paragraph:
    fragment_id: str
    text: str
    score: int = 0
    dropped: str | None = None  # reason when excluded by triage


@dataclass
class Window:
    node_id: str
    fragment_ids: list[str]
    text: str
    status: str = "PENDING"
    attempts: int = 0
    latency_ms: int = 0
    statements: list[dict[str, Any]] = field(default_factory=list)
    failure: str | None = None
    prompt_sha256: str = ""
    served_model: str = ""
    raw_output: str = ""


# --- triage ----------------------------------------------------------------------------------------


def paragraphs_from_fragments(data: bytes, fragments: list[dict[str, Any]]) -> list[Paragraph]:
    out: list[Paragraph] = []
    for f in fragments:
        fid = str(f.get("fragment_id", ""))
        if fid == "root":
            continue
        chunk = data[int(f["byte_start"]) : int(f["byte_end"])].decode("utf-8", errors="replace")
        # collapse runs of spaces but keep single newlines (table row boundaries)
        out.append(Paragraph(fid, "\n".join(" ".join(ln.split()) for ln in chunk.split("\n") if ln.strip())))
    return out


def signal_score(text: str) -> int:
    return 2 * len(_MONEY.findall(text)) + len(_PCT.findall(text)) + len(_KEYTERMS.findall(text))


def triage(paragraphs: list[Paragraph], *, min_chars: int = 60, max_chars: int = 6000) -> dict[str, int]:
    """Deterministic, model-free. Marks ``dropped`` and fills ``score``; returns counters."""
    counters = {"total": len(paragraphs), "short": 0, "boilerplate": 0, "no_signal": 0, "kept": 0, "too_long": 0}
    for p in paragraphs:
        if len(p.text) < min_chars and not (len(p.text) >= 24 and (_MONEY.search(p.text) or _PCT.search(p.text) or ("|" in p.text and re.search(r"\d{2,}", p.text)))):
            p.dropped, counters["short"] = "short", counters["short"] + 1
            continue
        if len(p.text) > max_chars:
            p.text = p.text[:max_chars]
            counters["too_long"] += 1
        if _BOILERPLATE.search(p.text):
            p.dropped, counters["boilerplate"] = "boilerplate", counters["boilerplate"] + 1
            continue
        p.score = signal_score(p.text)
        if p.score < 1:
            p.dropped, counters["no_signal"] = "no_signal", counters["no_signal"] + 1
            continue
        counters["kept"] += 1
    return counters


def build_windows(paragraphs: list[Paragraph], *, window_chars: int, max_windows: int) -> tuple[list[Window], int]:
    """Pack kept paragraphs (document order) into windows. If more than ``max_windows`` would result,
    raise the signal threshold until it fits (returns the threshold used)."""
    threshold = 1
    while True:
        kept = [p for p in paragraphs if not p.dropped and p.score >= threshold]
        windows: list[Window] = []
        cur: list[Paragraph] = []
        cur_len = 0
        for p in kept:
            if cur and cur_len + len(p.text) + 2 > window_chars:
                windows.append(cur)  # type: ignore[arg-type]
                cur, cur_len = [], 0
            cur.append(p)
            cur_len += len(p.text) + 2
        if cur:
            windows.append(cur)  # type: ignore[arg-type]
        if len(windows) <= max_windows or threshold > 50:
            break
        threshold += 1
    out = [
        Window(f"w{i + 1:04d}", [p.fragment_id for p in grp], "\n\n".join(p.text for p in grp))  # type: ignore[attr-defined]
        for i, grp in enumerate(windows)
    ]
    for p in paragraphs:
        if not p.dropped and p.score < threshold:
            p.dropped = f"below_threshold_{threshold}"
    return out, threshold


# --- atomic decision -----------------------------------------------------------------------------


def decision_messages(window_text: str, *, retry_hint: str | None = None) -> list[dict[str, str]]:
    sys = SYSTEM_PROMPT if not retry_hint else SYSTEM_PROMPT + " Previous answer was rejected: " + retry_hint + ". Return only the JSON object."
    return [{"role": "system", "content": sys}, {"role": "user", "content": "EXCERPT:\n" + window_text}]


def parse_decision(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object")
    obj = json.loads(text[start : end + 1])
    if isinstance(obj, dict) and isinstance(obj.get("statements"), list):
        cleaned = []
        for s in obj["statements"][:6]:
            if not isinstance(s, dict):
                continue
            cat = str(s.get("category", "OTHER")).upper().replace(" ", "_")
            s = {"text": " ".join(str(s.get("text", "")).split()), "category": cat if cat in CATEGORIES else "OTHER", "impact": s.get("impact", 3)}
            try:
                s["impact"] = max(1, min(5, int(round(float(s["impact"])))))
            except (TypeError, ValueError):
                s["impact"] = 3
            if len(s["text"]) > 400:
                s["text"] = s["text"][:397] + "..."
            cleaned.append(s)
        obj = {"statements": cleaned}
    errors = sorted(DECISION_VALIDATOR.iter_errors(obj), key=lambda e: list(e.path))
    if errors:
        raise ValueError(errors[0].message[:120])
    return obj


LLMCall = Callable[[list[dict[str, str]], int], Awaitable[tuple[str, str]]]  # (messages, max_tokens) -> (content, served_model)


async def run_window(window: Window, llm: LLMCall, *, max_attempts: int = 2, max_tokens: int = 520) -> Window:
    t0 = time.monotonic()
    hint: str | None = None
    for attempt in range(1, max_attempts + 1):
        window.attempts = attempt
        msgs = decision_messages(window.text, retry_hint=hint)
        window.prompt_sha256 = hashlib.sha256(json.dumps(msgs, sort_keys=True).encode()).hexdigest()
        try:
            content, served = await llm(msgs, max_tokens)
        except Exception as ex:  # upstream failure is a node failure, not a run failure
            window.failure = f"UPSTREAM:{type(ex).__name__}"
            hint = "upstream error"
            continue
        window.raw_output = content[:2000]
        window.served_model = served
        try:
            decision = parse_decision(content)
        except (ValueError, json.JSONDecodeError) as ex:
            window.failure = f"DECISION_INVALID:{str(ex)[:60]}"
            hint = str(ex)[:80]
            continue
        window.statements = decision["statements"]
        window.status = "COMMITTED"
        window.failure = None
        break
    else:
        window.status = "FAILED"
    window.latency_ms = int((time.monotonic() - t0) * 1000)
    return window


# --- reduce ---------------------------------------------------------------------------------------


def _norm_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9.%$]+", text.lower()) if len(t) > 2}


CATEGORY_CAP = 12  # deterministic diversity: at most this many statements per category in the top-N ...
OTHER_CAP = 4  # ... and fewer for the catch-all bucket


def reduce_statements(windows: list[Window], *, top_n: int, category_cap: int = CATEGORY_CAP, other_cap: int = OTHER_CAP) -> list[dict[str, Any]]:
    """Zero-model reduce: score = impact*2 + capped signal; Jaccard>0.6 dedupe; per-category cap; top-N.
    Overflow from capped categories back-fills the list when fewer than top_n remain."""
    cands: list[dict[str, Any]] = []
    for w in windows:
        if w.status != "COMMITTED":
            continue
        for s in w.statements:
            boost = min(3, signal_score(s["text"]))
            cands.append({**s, "node_id": w.node_id, "fragment_ids": w.fragment_ids, "score": s["impact"] * 2 + boost})
    cands.sort(key=lambda c: (-c["score"], c["node_id"]))
    deduped: list[dict[str, Any]] = []
    kept_tokens: list[set[str]] = []
    for c in cands:
        toks = _norm_tokens(c["text"])
        if not toks:
            continue
        if any(len(toks & k) / max(1, len(toks | k)) > 0.6 for k in kept_tokens):
            continue
        deduped.append(c)
        kept_tokens.append(toks)
    per_cat: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    for c in deduped:
        cap = other_cap if c["category"] == "OTHER" else category_cap
        if per_cat.get(c["category"], 0) < cap:
            kept.append(c)
            per_cat[c["category"]] = per_cat.get(c["category"], 0) + 1
        else:
            overflow.append(c)
        if len(kept) >= top_n:
            break
    if len(kept) < top_n:
        kept.extend(overflow[: top_n - len(kept)])
    for i, c in enumerate(kept, 1):
        c["rank"] = i
    return kept


# --- rendering ----------------------------------------------------------------------------------


def render_markdown_header(run_id: str, plan_hash: str, source: dict[str, Any], triage_counts: dict[str, int], n_windows: int, threshold: int) -> str:
    return (
        f"**forge-2b graph run** `{run_id}`  \n"
        f"DCS plan `{plan_hash}` · source `{source.get('file_id')}@{source.get('version')}` "
        f"({triage_counts['total']} paragraphs → {triage_counts['kept']} kept by deterministic triage, "
        f"signal ≥ {threshold} → {n_windows} atomic windows)\n\n"
        "**Execution log** (one line per atomic Qwen3.5-2B decision; a compact live graph is re-emitted as an artifact every ~20 s)\n\n"
    )


def render_progress_line(w: Window) -> str:
    frag = f"{w.fragment_ids[0]}–{w.fragment_ids[-1]}" if len(w.fragment_ids) > 1 else w.fragment_ids[0]
    mark = "✓" if w.status == "COMMITTED" else "✗"
    tail = f"{len(w.statements)} stmt" if w.status == "COMMITTED" else (w.failure or "failed")
    return f"- {mark} `{w.node_id}` {frag} · {tail} · {w.latency_ms} ms · attempts {w.attempts}\n"


def render_result_markdown(result: list[dict[str, Any]], windows: list[Window], run_id: str) -> str:
    committed = sum(1 for w in windows if w.status == "COMMITTED")
    failed = len(windows) - committed
    lines = ["\n---\n\n", f"## Most impactful statements (top {len(result)})\n\n"]
    for c in result:
        lines.append(f"{c['rank']}. **[{c['category']}·{c['impact']}]** {c['text']}  \n   <sub>node `{c['node_id']}` · {', '.join(c['fragment_ids'][:3])}{'…' if len(c['fragment_ids']) > 3 else ''}</sub>\n")
    lines.append(
        f"\n<sub>{committed} committed / {failed} failed window nodes · every statement above came from one atomic "
        f"Qwen3.5-2B decision over one window; ranking and dedupe are deterministic (zero_model). "
        f"Trace: `GET /v1/forge/runs/{run_id}`</sub>\n\n"
    )
    return "".join(lines)


def render_graph_html(trace: dict[str, Any]) -> str:
    """Self-contained interactive graph (SVG + vanilla JS). Open WebUI renders ```html blocks as an artifact."""
    data = json.dumps(trace, ensure_ascii=False).replace("</", "<\\/")
    return (
        "```html\n<!doctype html><html><head><meta charset='utf-8'><title>forge-2b execution graph</title>"
        "<style>body{font:13px system-ui,sans-serif;margin:0;display:grid;grid-template-columns:1fr 380px;height:100vh}"
        "#g{overflow:auto;padding:10px}#d{border-left:1px solid #ddd;padding:10px;overflow:auto;background:#fafafa}"
        "@media(max-width:760px){body{grid-template-columns:1fr;grid-template-rows:auto 1fr}#d{border-left:0;border-top:1px solid #ddd}}"
        "rect{cursor:pointer}pre{white-space:pre-wrap;font-size:11px;background:#fff;border:1px solid #eee;padding:6px;max-height:40vh;overflow:auto}"
        ".k{color:#666}h3{margin:4px 0}</style></head><body><div id='g'></div><div id='d'><h3>forge-2b graph</h3>"
        "<div class='k'>Click a node. Green = committed window, red = failed, grey = zero-model stage.</div></div>"
        "<script>const T=" + data + ";"
        "const W=T.windows||[],cols=Math.max(8,Math.ceil(Math.sqrt(W.length*2))),cw=26,ch=18,gx=16,gy=60;"
        "const stages=[['source',T.source&&T.source.file_id||'source'],['plan',(T.plan_hash||'').slice(0,19)],['triage',(T.triage&&T.triage.kept||0)+' kept']];"
        "const H=gy+ch*Math.ceil(W.length/cols)+120,Wd=Math.max(640,cols*cw+40);"
        "let s=`<svg width='${Wd}' height='${H}' xmlns='http://www.w3.org/2000/svg'>`;"
        "function box(x,y,w,h,f,id,l){return `<rect x='${x}' y='${y}' width='${w}' height='${h}' rx='4' fill='${f}' stroke='#555' data-id='${id}'></rect><text x='${x+6}' y='${y+13}' font-size='11' pointer-events='none'>${l}</text>`}"
        "stages.forEach((st,i)=>{s+=box(16+i*190,10,170,30,'#e8e8e8',st[0],st[0]+': '+st[1]);if(i)s+=`<line x1='${16+i*190-20}' y1='25' x2='${16+i*190}' y2='25' stroke='#999' marker-end='url(#a)'/>`});"
        "s+=`<defs><marker id='a' markerWidth='8' markerHeight='8' refX='6' refY='3' orient='auto'><path d='M0,0 L6,3 L0,6 z' fill='#999'/></marker></defs>`;"
        "W.forEach((w,i)=>{const x=16+(i%cols)*cw,y=gy+Math.floor(i/cols)*ch;const f=w.status==='COMMITTED'?(w.statements.length?'#7cc47c':'#cfe8cf'):'#e88';s+=`<rect x='${x}' y='${y}' width='${cw-3}' height='${ch-3}' rx='3' fill='${f}' stroke='#444' data-id='${w.node_id}'><title>${w.node_id} ${w.status} ${w.statements.length} stmt</title></rect>`});"
        "const ry=gy+ch*Math.ceil(W.length/cols)+20;s+=box(16,ry,170,30,'#e8e8e8','reduce','reduce: '+(T.result||[]).length+' ranked');s+=box(206,ry,170,30,T.status==='COMMITTED'?'#7cc47c':'#e88','result','result: '+T.status);s+='</svg>';"
        "document.getElementById('g').innerHTML=s;"
        "function esc(t){return String(t).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}"
        "document.getElementById('g').addEventListener('click',e=>{const id=e.target.getAttribute&&e.target.getAttribute('data-id');if(!id)return;const d=document.getElementById('d');"
        "const w=W.find(x=>x.node_id===id);if(w){d.innerHTML=`<h3>${id} · ${w.status}</h3><div class='k'>fragments ${w.fragment_ids.join(', ')} · ${w.latency_ms} ms · attempts ${w.attempts} · model ${esc(w.served_model||'')}</div><b>Input (window)</b><pre>${esc(w.input_preview||'')}</pre><b>Atomic prompt sha256</b><pre>${w.prompt_sha256}</pre><b>Output</b><pre>${esc(JSON.stringify(w.statements,null,1))}</pre>${w.failure?'<b>Failure</b><pre>'+esc(w.failure)+'</pre>':''}`;return}"
        "const map={source:T.source,plan:{plan_hash:T.plan_hash,intent:T.plan_intent},triage:T.triage,reduce:{top_n:(T.result||[]).length,rule:'score=impact*2+signal, jaccard>0.6 dedupe'},result:{status:T.status,statements:(T.result||[]).slice(0,10)}};"
        "d.innerHTML=`<h3>${id}</h3><pre>${esc(JSON.stringify(map[id]||{},null,1))}</pre>`});"
        "</script></body></html>\n```\n"
    )


def html_escape(s: str) -> str:
    return html.escape(s, quote=True)
