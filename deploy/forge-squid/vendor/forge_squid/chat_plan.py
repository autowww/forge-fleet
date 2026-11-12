"""Compile and execute multi-step chat response plans (ChatTaskDAG)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from . import env_keys
from .chat_comprehend import ScopedObjective, emit_comprehension_band
from .chat_lane import Reading, system_prompt, visible_prefix, scrub_self_claim, footer
from .execution_graph import ExecutionGraph
from .prose_turn import ProseProfile, assemble_prose, gate as prose_gate, profile_instruction

ChatPlanMode = Literal["on", "off", "single"]


def chat_plan_enabled() -> bool:
    v = (env_keys.squid_env("CHAT_PLAN", default="on")).strip().lower()
    return v not in ("0", "off", "false", "single")


def chat_max_model_calls() -> int:
    try:
        return max(1, env_keys.squid_env_int("CHAT_MAX_MODEL_CALLS", 3))
    except ValueError:
        return 3


@dataclass
class PlanNode:
    id: str
    kind: str
    route_pref: str
    depends_on: list[str]
    scope: str
    lane: str = "execute"
    routing: str = "zero_model"


@dataclass
class ChatTaskDAG:
    nodes: list[PlanNode] = field(default_factory=list)
    output_shape: list[str] = field(default_factory=list)
    model_calls_planned: int = 0
    agent_role: str = "composer"
    multi: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_role": self.agent_role,
            "multi": self.multi,
            "model_calls_planned": self.model_calls_planned,
            "output_shape": self.output_shape,
            "nodes": [
                {
                    "id": n.id,
                    "kind": n.kind,
                    "route_pref": n.route_pref,
                    "depends_on": n.depends_on,
                    "scope": n.scope,
                    "lane": n.lane,
                }
                for n in self.nodes
            ],
        }


def agent_role_from_alias(model_alias: str) -> str:
    low = (model_alias or "").lower()
    if "composer" in low:
        return "orchestrator"
    return "responder"


def compile_plan(
    user_text: str,
    reading: Reading,
    objectives: list[ScopedObjective],
    prose_prof: ProseProfile,
    model_alias: str,
    *,
    structured: bool,
) -> ChatTaskDAG:
    role = agent_role_from_alias(model_alias)
    if structured or not chat_plan_enabled() or len(objectives) < 2:
        return _single_plan(user_text, prose_prof, role)
    nodes: list[PlanNode] = []
    out_ids: list[str] = []
    for i, obj in enumerate(objectives[: chat_max_model_calls()]):
        nid = f"llm_{obj.id}"
        nodes.append(
            PlanNode(
                nid,
                "llm",
                "D1",
                [f"llm_{objectives[i - 1].id}"] if i else ["plan_compile"],
                obj.user_slice,
                lane="execute",
                routing="fixed_model",
            )
        )
        out_ids.append(nid)
    nodes.append(
        PlanNode("synthesize", "llm", "D2", out_ids, "Merge prior sections into one coherent answer", routing="fixed_model")
    )
    nodes.append(PlanNode("prose_gate", "gate", "D0", ["synthesize"], "prose_gate", lane="gate", routing="zero_model"))
    nodes.append(PlanNode("merge", "d0_shape", "D0", ["prose_gate"], "assemble prose sections", lane="merge", routing="zero_model"))
    planned = sum(1 for n in nodes if n.routing == "fixed_model")
    return ChatTaskDAG(
        nodes=nodes,
        output_shape=out_ids + ["synthesize"],
        model_calls_planned=planned,
        agent_role=role,
        multi=True,
    )


def _single_plan(user_text: str, prose_prof: ProseProfile, role: str) -> ChatTaskDAG:
    nodes = [
        PlanNode("reply", "llm", "D1", ["plan_compile"], user_text[:200], routing="fixed_model"),
        PlanNode("prose_gate", "gate", "D0", ["reply"], "prose_gate", lane="gate", routing="zero_model"),
        PlanNode("merge", "d0_shape", "D0", ["prose_gate"], "assemble prose", lane="merge", routing="zero_model"),
    ]
    return ChatTaskDAG(
        nodes=nodes,
        output_shape=["reply"],
        model_calls_planned=1,
        agent_role=role,
        multi=False,
    )


def emit_plan_band(eg: ExecutionGraph, plan: ChatTaskDAG) -> None:
    eg.add("plan_compile", "zero_model", "ChatTaskDAG", lane="plan", kind="plan_compile")
    eg.finish(
        "plan_compile",
        "COMMITTED",
        f"role {plan.agent_role} · {plan.model_calls_planned} LLM · multi={plan.multi}",
    )
    eg.add_edge("route", "plan_compile")
    for n in plan.nodes:
        eg.add(n.id, n.routing, n.route_pref, lane=n.lane, kind=n.kind)
        for dep in n.depends_on:
            if dep == "plan_compile":
                eg.add_edge("plan_compile", n.id)
            else:
                try:
                    eg.get(dep)
                    eg.add_edge(dep, n.id)
                except StopIteration:
                    pass


def _topo(plan: ChatTaskDAG) -> list[PlanNode]:
    ids = {n.id for n in plan.nodes}
    preds = {n.id: [d for d in n.depends_on if d in ids or d == "plan_compile"] for n in plan.nodes}
    done: set[str] = set()
    order: list[PlanNode] = []
    by_id = {n.id: n for n in plan.nodes}
    while len(order) < len(plan.nodes):
        progressed = False
        for n in plan.nodes:
            if n.id in done:
                continue
            ok = all(d in done or d == "plan_compile" for d in n.depends_on)
            if ok:
                order.append(n)
                done.add(n.id)
                progressed = True
        if not progressed:
            order.extend(n for n in plan.nodes if n.id not in done)
            break
    return order


LLMCallback = Callable[[list[dict[str, str]]], Awaitable[tuple[str, str]]]


async def execute_chat_plan(
    eg: ExecutionGraph,
    plan: ChatTaskDAG,
    *,
    user_text: str,
    reading: Reading,
    prose_prof: ProseProfile,
    conv: list[dict[str, str]],
    structured: bool,
    call_llm: LLMCallback,
    system_base: str,
) -> tuple[str, list[str], int]:
    """Run plan nodes; return merged user text, prose gate failures, model call count."""
    outputs: dict[str, str] = {}
    calls = 0
    gate_fails: list[str] = []
    for pnode in _topo(plan):
        if pnode.kind == "llm" and pnode.routing == "fixed_model":
            eg.start(pnode.id, pnode.scope[:60])
            prior = "\n\n".join(f"### {k}\n{v}" for k, v in outputs.items()) if outputs else ""
            scope_msg = (
                f"Answer only this part of the user's question (do not answer other parts yet):\n{pnode.scope}\n\n"
                f"User's full question for context:\n{user_text[:1500]}"
            )
            if prior:
                scope_msg += f"\n\nPrior sections already written (do not repeat verbatim):\n{prior[:2000]}"
            sys = system_base + profile_instruction(prose_prof if not structured else ProseProfile.PLAIN)
            msgs = [{"role": "system", "content": sys}, *conv, {"role": "user", "content": scope_msg}]
            piece, _served = await call_llm(msgs)
            calls += 1
            outputs[pnode.id] = piece.strip()
            eg.finish(pnode.id, "COMMITTED", f"{len(piece)} chars")
        elif pnode.kind == "gate":
            eg.start(pnode.id, "prose gates")
            draft = "\n\n".join(outputs.get(k, "") for k in plan.output_shape if k in outputs)
            draft = visible_prefix(reading) + scrub_self_claim(draft) + footer(reading)
            if not structured:
                draft = assemble_prose(prose_prof, draft)
            gate_fails = prose_gate(prose_prof, draft, truncated=False)
            st = "COMMITTED" if not gate_fails else "PARTIAL"
            eg.finish(pnode.id, st, ", ".join(gate_fails) or "passed")
            outputs[pnode.id] = draft
        elif pnode.kind == "d0_shape":
            eg.start(pnode.id, "merge sections")
            text = outputs.get("prose_gate") or "\n\n".join(
                outputs.get(k, "") for k in plan.output_shape if k in outputs
            )
            if not structured:
                text = assemble_prose(prose_prof, text)
            text = visible_prefix(reading) + scrub_self_claim(text.strip()) + footer(reading)
            eg.finish(pnode.id, "COMMITTED", f"{len(text)} chars out")
            outputs[pnode.id] = text
    final = outputs.get("merge") or outputs.get("prose_gate") or ""
    if not final and outputs:
        final = list(outputs.values())[-1]
    return final, gate_fails, calls


def bootstrap_graph(run_id: str, user_text: str, reading: Reading, decision: str) -> tuple[ExecutionGraph, list[ScopedObjective]]:
    eg = ExecutionGraph(run_id, "chat")
    objectives = emit_comprehension_band(eg, user_text, reading, decision)
    return eg, objectives
