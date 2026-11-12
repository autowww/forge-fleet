"""Live execution graph for streamed runs.

Open WebUI turns every *closed* ```html block into a new artifact version and auto-selects the newest one while the
message streams (Chat.svelte getContents -> Artifacts.svelte). We exploit that: a compact vertical graph is emitted
at the start of a run, re-emitted on every node transition, and once more at the end. Each snapshot embeds the
elapsed time at render and a tiny script that keeps the RUNNING node's timer ticking in the browser, so the operator
sees when the LLM is being called, which engine each node uses, and how long each step took.

Routing classes:
  zero_model  - deterministic Python (parser, token-overlap retriever, lexicon scan, SHA verification): no model at all
  dcs         - forge-dcs HTTP calls (deterministic plan compile / fragments)
  fixed_model - an atomic LLM call to the pinned backend model (the only neural model in this PoC)
"""

from __future__ import annotations

import html
import time
from dataclasses import dataclass, field
from typing import Any

SNAP_PREFIX = "\n```html\n<!doctype html><html><head><meta charset=\"utf-8\"><title>forge-squid live graph</title>"


def is_live_snapshot(piece: str) -> bool:
    """True for a non-final snapshot block (JSON/non-stream clients only need the final one)."""
    return piece.startswith(SNAP_PREFIX) and "· live snapshot</div>" in piece


ROUTING_LABEL = {"zero_model": "deterministic · no model", "dcs": "forge-dcs · deterministic", "fixed_model": "LLM call"}
COLOR = {"COMMITTED": "#2e7d32", "PARTIAL": "#b26a00", "FAILED": "#c62828", "SKIPPED": "#9e9e9e", "RUNNING": "#ef6c00", "PENDING": "#90a4ae"}
FILL = {"COMMITTED": "#e8f5e9", "PARTIAL": "#fff8e1", "FAILED": "#ffebee", "SKIPPED": "#f5f5f5", "RUNNING": "#fff3e0", "PENDING": "#ffffff"}
ICON = {"COMMITTED": "✓", "PARTIAL": "◐", "FAILED": "✗", "SKIPPED": "–", "RUNNING": "▶", "PENDING": "·"}


@dataclass
class Node:
    id: str
    routing: str
    engine: str
    status: str = "PENDING"
    detail: str = ""
    t_start: float | None = None
    t_end: float | None = None
    done: int = 0
    total: int = 0

    @property
    def ms(self) -> int | None:
        if self.t_start is None:
            return None
        return int(((self.t_end if self.t_end is not None else time.monotonic()) - self.t_start) * 1000)


@dataclass
class LiveGraph:
    run_id: str
    lane: str
    nodes: list[Node] = field(default_factory=list)
    t0: float = field(default_factory=time.monotonic)
    status: str = "RUNNING"

    # --- state -------------------------------------------------------------------------------------------
    def add(self, node_id: str, routing: str, engine: str, *, total: int = 0) -> Node:
        n = Node(node_id, routing, engine, total=total)
        self.nodes.append(n)
        return n

    def get(self, node_id: str) -> Node:
        return next(n for n in self.nodes if n.id == node_id)

    def start(self, node_id: str, detail: str = "") -> Node:
        n = self.get(node_id)
        n.status, n.detail, n.t_start = "RUNNING", detail, time.monotonic()
        return n

    def finish(self, node_id: str, status: str, detail: str = "") -> Node:
        n = self.get(node_id)
        if n.t_start is None:
            n.t_start = time.monotonic()
        n.status, n.t_end = status, time.monotonic()
        if detail:
            n.detail = detail
        return n

    def progress(self, node_id: str, done: int, total: int, detail: str = "") -> Node:
        n = self.get(node_id)
        n.done, n.total = done, total
        if detail:
            n.detail = detail
        return n

    def close(self, status: str) -> None:
        self.status = status

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.t0) * 1000)

    # --- markdown timeline ---------------------------------------------------------------------------------
    def line(self, n: Node, event: str) -> str:
        """One timeline line: '- ▶ 0.02 s `decide` — LLM call: qwen… (attempt 1)' / '- ✓ 5.18 s `decide` COMMITTED (5160 ms) — …'."""
        t = f"{self.elapsed_ms() / 1000:6.2f} s"
        if event == "start":
            return f"- ▶ `{t}` **{n.id}** — {ROUTING_LABEL.get(n.routing, n.routing)}: {n.engine}" + (f" — {n.detail}" if n.detail else "") + "\n"
        dur = f" ({n.ms} ms)" if n.ms is not None else ""
        return f"- {ICON.get(n.status, '·')} `{t}` **{n.id}** {n.status}{dur}" + (f" — {n.detail}" if n.detail else "") + "\n"

    def steps(self) -> list[dict[str, Any]]:
        """Trace/record representation (same shape the execution log and tests use)."""
        return [{"node": n.id, "routing": n.routing, "status": n.status, "detail": n.detail, "engine": n.engine,
                 "ms": n.ms, **({"done": n.done, "total": n.total} if n.total else {})} for n in self.nodes]

    # --- artifact snapshot -----------------------------------------------------------------------------------
    def snapshot_html(self, *, final: bool = False) -> str:
        bw, bh, gap, x = 440, 78, 24, 8
        now_ms = self.elapsed_ms()
        boxes: list[str] = []
        for i, n in enumerate(self.nodes):
            y = 8 + i * (bh + gap)
            color, fill = COLOR.get(n.status, "#1565c0"), FILL.get(n.status, "#ffffff")
            detail = n.detail if len(n.detail) <= 66 else n.detail[:63] + "…"
            engine = n.engine if len(n.engine) <= 58 else n.engine[:55] + "…"
            if n.status == "RUNNING":
                timing = f'<tspan class="tick" data-ms="{n.ms or 0}">{(n.ms or 0) / 1000:.1f} s</tspan>'
            elif n.ms is not None:
                timing = f"{n.ms} ms"
            else:
                timing = ""
            prog = ""
            if n.total:
                pw = int((bw - 24) * min(n.done, n.total) / n.total)
                prog = (f'<rect x="{x + 12}" y="{y + bh - 9}" width="{bw - 24}" height="4" rx="2" fill="#eceff1"/>'
                        f'<rect x="{x + 12}" y="{y + bh - 9}" width="{pw}" height="4" rx="2" fill="{color}"/>')
            boxes.append(
                f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="8" fill="{fill}" stroke="{color}" stroke-width="2"/>'
                f'<text x="{x + 12}" y="{y + 20}" font-family="monospace" font-size="14" font-weight="bold">{html.escape(n.id)}'
                f'<tspan fill="{color}" font-family="sans-serif" font-size="11" font-weight="bold"> {ICON.get(n.status, "")} {html.escape(n.status)}</tspan></text>'
                f'<text x="{x + bw - 12}" y="{y + 20}" text-anchor="end" font-family="monospace" font-size="12" fill="{color}">{timing}</text>'
                f'<text x="{x + 12}" y="{y + 38}" font-family="sans-serif" font-size="11" fill="#555">{html.escape(ROUTING_LABEL.get(n.routing, n.routing))} · {html.escape(engine)}</text>'
                f'<text x="{x + 12}" y="{y + 56}" font-family="sans-serif" font-size="11" fill="#333">{html.escape(detail)}</text>'
                + prog
            )
            if i:
                cx = x + bw // 2
                boxes.append(f'<line x1="{cx}" y1="{y - gap}" x2="{cx}" y2="{y}" stroke="#555" stroke-width="2" marker-end="url(#a)"/>')
        width, height = bw + 2 * x, 16 + len(self.nodes) * (bh + gap) - gap
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {width} {height}" style="max-width:{width}px;display:block">'
            '<defs><marker id="a" markerWidth="8" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#555"/></marker></defs>'
            + "".join(boxes) + "</svg>"
        )
        total = (f'<span class="tick" data-ms="{now_ms}">{now_ms / 1000:.1f} s</span>' if self.status == "RUNNING"
                 else f"{now_ms / 1000:.1f} s · {html.escape(self.status)}")
        llm = sum(1 for n in self.nodes if n.routing == "fixed_model" and n.status in ("RUNNING", "COMMITTED", "PARTIAL", "FAILED"))
        script = ("<script>(function(){var b=Date.now();setInterval(function(){document.querySelectorAll('.tick').forEach(function(e){"
                  "e.textContent=((+e.getAttribute('data-ms')+Date.now()-b)/1000).toFixed(1)+' s'})},200)})()</script>"
                  if self.status == "RUNNING" else "")
        legend = ('<div style="font-size:11px;color:#555;margin:6px 0 8px">'
                  '<span style="color:#ef6c00">▶ running</span> · <span style="color:#2e7d32">✓ committed</span> · <span style="color:#b26a00">◐ partial</span> · '
                  '<span style="color:#c62828">✗ failed</span> · <span style="color:#9e9e9e">– skipped</span> · '
                  'orange/green border = LLM call · grey = forge-squid comprehension / prompt / polish</div>')
        head = (f'<div style="font-size:12px;color:#333"><b>forge-squid {html.escape(self.lane)} lane</b> · run <code>{self.run_id}</code>'
                f'<br>elapsed {total} · LLM nodes touched: {llm} · {"final" if final else "live snapshot"}</div>')
        return (
            "\n```html\n<!doctype html><html><head><meta charset=\"utf-8\"><title>forge-squid live graph</title></head>"
            f"<body style=\"font-family:sans-serif;margin:8px\">{head}{legend}{svg}{script}</body></html>\n```\n"
        )
