"""DAG execution graph for chat lane artifacts (comprehension → plan → execute → merge)."""
from __future__ import annotations

import html
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from . import live

LANES = ("comprehend", "plan", "execute", "gate", "merge")
LANE_FILL = {
    "comprehend": "#e3f2fd",
    "plan": "#f3e5f5",
    "execute": "#fff3e0",
    "gate": "#fff8e1",
    "merge": "#e8f5e9",
}


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""


@dataclass
class ExecutionGraph:
    run_id: str
    lane: str
    nodes: list[live.Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    node_lane: dict[str, str] = field(default_factory=dict)
    node_kind: dict[str, str] = field(default_factory=dict)
    t0: float = field(default_factory=time.monotonic)
    status: str = "RUNNING"

    def add(
        self,
        node_id: str,
        routing: str,
        engine: str,
        *,
        lane: str = "execute",
        kind: str = "step",
        total: int = 0,
    ) -> live.Node:
        n = live.Node(node_id, routing, engine, total=total)
        self.nodes.append(n)
        self.node_lane[node_id] = lane
        self.node_kind[node_id] = kind
        return n

    def add_edge(self, src: str, dst: str, label: str = "") -> None:
        self.edges.append(Edge(src, dst, label))

    def get(self, node_id: str) -> live.Node:
        return next(n for n in self.nodes if n.id == node_id)

    def start(self, node_id: str, detail: str = "") -> live.Node:
        n = self.get(node_id)
        n.status, n.detail, n.t_start = "RUNNING", detail, time.monotonic()
        return n

    def finish(self, node_id: str, status: str, detail: str = "") -> live.Node:
        n = self.get(node_id)
        if n.t_start is None:
            n.t_start = time.monotonic()
        n.status, n.t_end = status, time.monotonic()
        if detail:
            n.detail = detail
        return n

    def close(self, status: str) -> None:
        self.status = status

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.t0) * 1000)

    def line(self, n: live.Node, event: str) -> str:
        t = f"{self.elapsed_ms() / 1000:6.2f} s"
        if event == "start":
            return (
                f"- ▶ `{t}` **{n.id}** — {live.ROUTING_LABEL.get(n.routing, n.routing)}: {n.engine}"
                + (f" — {n.detail}" if n.detail else "")
                + "\n"
            )
        dur = f" ({n.ms} ms)" if n.ms is not None else ""
        return (
            f"- {live.ICON.get(n.status, '·')} `{t}` **{n.id}** {n.status}{dur}"
            + (f" — {n.detail}" if n.detail else "")
            + "\n"
        )

    def steps(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for n in self.nodes:
            row = {
                "node": n.id,
                "routing": n.routing,
                "status": n.status,
                "detail": n.detail,
                "engine": n.engine,
                "ms": n.ms,
                "lane": self.node_lane.get(n.id, "execute"),
                "kind": self.node_kind.get(n.id, "step"),
            }
            if n.total:
                row["done"], row["total"] = n.done, n.total
            out.append(row)
        return out

    def to_trace(self) -> dict[str, Any]:
        return {
            "nodes": self.steps(),
            "edges": [{"from": e.src, "to": e.dst, "label": e.label} for e in self.edges],
        }

    def _layers(self) -> dict[str, int]:
        ids = {n.id for n in self.nodes}
        preds: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for e in self.edges:
            if e.dst in ids and e.src in ids:
                preds[e.dst].append(e.src)
        layer: dict[str, int] = {}

        def depth(nid: str, seen: set[str]) -> int:
            if nid in layer:
                return layer[nid]
            if nid in seen:
                return 0
            seen.add(nid)
            if not preds[nid]:
                layer[nid] = 0
                return 0
            d = max(depth(p, seen) for p in preds[nid]) + 1
            layer[nid] = d
            return d

        for n in self.nodes:
            depth(n.id, set())
        return layer

    def snapshot_html(self, *, final: bool = False) -> str:
        bw, bh, hgap, vgap, pad = 168, 64, 28, 18, 8
        layers = self._layers()
        by_layer: dict[int, list[live.Node]] = defaultdict(list)
        for n in self.nodes:
            by_layer[layers[n.id]].append(n)
        max_layer = max(by_layer.keys()) if by_layer else 0
        positions: dict[str, tuple[float, float]] = {}
        svg_parts: list[str] = []
        lane_bands: list[str] = []
        y0 = 12
        for col in range(max_layer + 1):
            row = by_layer.get(col, [])
            row_h = max(1, len(row))
            total_w = row_h * (bw + hgap) - hgap
            x_start = pad + max(0, (max((len(by_layer[i]) for i in range(max_layer + 1)), default=1) * (bw + hgap) - total_w) // 2)
            for i, n in enumerate(row):
                x = x_start + i * (bw + hgap)
                y = y0 + col * (bh + vgap)
                positions[n.id] = (x + bw / 2, y + bh / 2)
                color = live.COLOR.get(n.status, "#1565c0")
                fill = live.FILL.get(n.status, "#ffffff")
                band = self.node_lane.get(n.id, "execute")
                if n.status == "PENDING":
                    fill = LANE_FILL.get(band, fill)
                kind = self.node_kind.get(n.id, "")
                detail = n.detail if len(n.detail) <= 52 else n.detail[:49] + "…"
                engine = n.engine if len(n.engine) <= 40 else n.engine[:37] + "…"
                if n.status == "RUNNING":
                    timing = f'<tspan class="tick" data-ms="{n.ms or 0}">{(n.ms or 0) / 1000:.1f} s</tspan>'
                elif n.ms is not None:
                    timing = f"{n.ms} ms"
                else:
                    timing = ""
                gate_shape = ""
                if kind == "gate":
                    cx, cy = x + bw / 2, y + bh / 2
                    s = min(bw, bh) / 2 - 4
                    gate_shape = (
                        f'<polygon points="{cx},{cy - s} {cx + s},{cy} {cx},{cy + s} {cx - s},{cy}" '
                        f'fill="{fill}" stroke="{color}" stroke-width="2"/>'
                    )
                if gate_shape:
                    svg_parts.append(gate_shape)
                    svg_parts.append(
                        f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" font-family="monospace" font-size="11" font-weight="bold">'
                        f'{html.escape(n.id)} {live.ICON.get(n.status, "")}</text>'
                    )
                else:
                    svg_parts.append(
                        f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="6" fill="{fill}" stroke="{color}" stroke-width="2"/>'
                        f'<text x="{x + 8}" y="{y + 18}" font-family="monospace" font-size="12" font-weight="bold">{html.escape(n.id)}'
                        f'<tspan fill="{color}" font-size="10"> {live.ICON.get(n.status, "")} {html.escape(n.status)}</tspan></text>'
                        f'<text x="{x + bw - 8}" y="{y + 18}" text-anchor="end" font-size="10" fill="{color}">{timing}</text>'
                        f'<text x="{x + 8}" y="{y + 34}" font-size="10" fill="#555">{html.escape(live.ROUTING_LABEL.get(n.routing, n.routing))}</text>'
                        f'<text x="{x + 8}" y="{y + 48}" font-size="10" fill="#333">{html.escape(detail or engine)}</text>'
                        f'<text x="{x + 8}" y="{y + 60}" font-size="9" fill="#888">{html.escape(band)} · {html.escape(kind)}</text>'
                    )
        for e in self.edges:
            if e.src not in positions or e.dst not in positions:
                continue
            x1, y1 = positions[e.src]
            x2, y2 = positions[e.dst]
            svg_parts.append(
                f'<line x1="{x1}" y1="{y1 + bh / 2}" x2="{x2}" y2="{y2 - bh / 2}" stroke="#555" stroke-width="1.5" marker-end="url(#a)"/>'
            )
            if e.label:
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                svg_parts.append(f'<text x="{mx}" y="{my}" font-size="9" fill="#666">{html.escape(e.label)}</text>')
        width = pad * 2 + max((len(by_layer[i]) for i in range(max_layer + 1)), default=1) * (bw + hgap)
        height = y0 + (max_layer + 1) * (bh + vgap) + pad
        seen_lanes = []
        for lane in LANES:
            if any(self.node_lane.get(n.id) == lane for n in self.nodes):
                seen_lanes.append(lane)
        lane_hdr = " · ".join(seen_lanes) if seen_lanes else "execute"
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {width} {height}" style="max-width:{width}px;display:block">'
            '<defs><marker id="a" markerWidth="8" markerHeight="8" refX="8" refY="4" orient="auto">'
            '<path d="M0,0 L8,4 L0,8 z" fill="#555"/></marker></defs>'
            + "".join(svg_parts)
            + "</svg>"
        )
        now_ms = self.elapsed_ms()
        total = (
            f'<span class="tick" data-ms="{now_ms}">{now_ms / 1000:.1f} s</span>'
            if self.status == "RUNNING" and not final
            else f"{now_ms / 1000:.1f} s · {html.escape(self.status)}"
        )
        llm = sum(
            1
            for n in self.nodes
            if n.routing == "fixed_model" and n.status in ("RUNNING", "COMMITTED", "PARTIAL", "FAILED")
        )
        script = ""
        if self.status == "RUNNING" and not final:
            script = (
                "<script>(function(){var b=Date.now();setInterval(function(){"
                "document.querySelectorAll('.tick').forEach(function(e){"
                'e.textContent=((+e.getAttribute("data-ms")+Date.now()-b)/1000).toFixed(1)+" s"})},200)})()</script>'
            )
        legend = (
            '<div style="font-size:11px;color:#555;margin:6px 0 8px">'
            '<span style="color:#ef6c00">▶ running</span> · <span style="color:#2e7d32">✓ committed</span> · '
            'lanes: <b>' + html.escape(lane_hdr) + "</b> · "
            "diamond = gate · orange/green border = LLM</div>"
        )
        head = (
            f'<div style="font-size:12px;color:#333"><b>forge-squid {html.escape(self.lane)} DAG</b> · run <code>{self.run_id}</code>'
            f"<br>elapsed {total} · LLM nodes touched: {llm} · {'final' if final else 'live snapshot'}</div>"
        )
        return (
            "\n```html\n<!doctype html><html><head><meta charset=\"utf-8\"><title>forge-squid live graph</title></head>"
            f"<body style=\"font-family:sans-serif;margin:8px\">{head}{legend}{svg}{script}</body></html>\n```\n"
        )
