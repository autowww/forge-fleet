"""Deterministic semantic validation of a PlanIR graph (I1–I4 and structural integrity).

JSON Schema validates shape only. This module enforces:

- I1 ``BINDING_UNAUTHORIZED``: a binding may only read from a node that has an explicit edge
  ``from_node -> node`` carrying that binding alias.
- I2 ``BINDING_DEPENDS_MISMATCH``: binding ``from_node`` must be listed in ``depends_on``.
- I3 ``FRAGMENT_REF_MALFORMED`` / ``FRAGMENT_VERSION_UNKNOWN`` / ``FRAGMENT_NOT_REGISTERED`` /
  ``SOURCE_SCOPE_VIOLATION`` / ``SOURCE_UNKNOWN``: every fragment ref must parse as
  ``<file_id>@<version>#root``, name an exact ``source_versions`` entry, and that entry's
  ``<file_id>@<content_hash>`` must be in the node's ``source_scope``. ``#root`` always
  exists; any other fragment must be present in the registry index passed by the caller.
  ``SOURCE_SCOPE_UNBOUND`` (P02, F1): every ``source_scope`` entry must be bound by at least
  one fragment ref — scope is an upper authorization bound, never an implicit input list.
- I4 ``DUPLICATE_NODE_ID``, ``DANGLING_DEPENDENCY``, ``DEPENDS_ON_DUPLICATE``,
  ``EDGE_DEPENDS_MISMATCH``, ``EDGE_DUPLICATE``, ``EDGE_UNEXPECTED``, ``CYCLE_DETECTED``,
  ``TOPOLOGICAL_ORDER_UNSTABLE``. The declared edge set must be *exactly* the set derived from
  ``depends_on`` + ``input_bindings`` (one edge per binding alias; one control edge per
  unbound dependency); nothing more, nothing less, nothing twice.
- ``BINDING_PATH_INVALID``, ``BINDING_DUPLICATE_ALIAS``, ``BINDING_SCHEMA_MISMATCH``,
  ``ZERO_MODEL_HAS_MODEL_POLICY``, ``DUPLICATE_SOURCE_ID``.

Pure functions; no I/O. The compiler runs this *before* computing ``plan_hash``.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from forge_dcs import errors

_OUTPUT_PATH = re.compile(r"^\$(\.[A-Za-z_][A-Za-z0-9_]*){1,8}$")
_IDENT = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
_FRAGMENT_REF = re.compile(rf"^(?P<file_id>{_IDENT})@(?P<version>{_IDENT})#(?P<fragment>{_IDENT})$")
ROOT_FRAGMENT = "root"

EdgeKey = tuple[str, str, str | None]


@dataclass(frozen=True)
class GraphError:
    code: str
    message: str
    node_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def parse_fragment_ref(ref: str) -> tuple[str, str, str] | None:
    """Bounded grammar ``file_id@version#fragment``; returns None when malformed."""
    m = _FRAGMENT_REF.match(str(ref))
    if not m:
        return None
    return m.group("file_id"), m.group("version"), m.group("fragment")


def expected_edges(tasks: list[dict[str, Any]]) -> Counter[EdgeKey]:
    """The only edge set a plan may declare, derived from depends_on + input_bindings.

    For each node and each dependency ``d``: one edge per binding alias read from ``d``; if the
    node reads nothing from ``d``, exactly one control edge ``(d, node, None)``.
    Bindings whose ``from_node`` is not a dependency are excluded here (I2 reports them).
    """
    exp: Counter[EdgeKey] = Counter()
    for t in tasks:
        nid = t["node_id"]
        deps = list(t.get("depends_on") or [])
        by_dep: dict[str, list[str]] = {}
        for b in t.get("input_bindings") or []:
            by_dep.setdefault(b.get("from_node"), []).append(b.get("bind_as"))
        for d in dict.fromkeys(deps):  # de-duplicated, order preserved
            aliases = by_dep.get(d)
            if aliases:
                for a in aliases:
                    exp[(d, nid, a)] += 1
            else:
                exp[(d, nid, None)] += 1
    return exp


def topological_order(node_ids: list[str], depends_on: dict[str, list[str]]) -> list[str] | None:
    """Kahn's algorithm with lexicographic tie-break. Returns None when a cycle exists."""
    indeg = {n: 0 for n in node_ids}
    children: dict[str, list[str]] = {n: [] for n in node_ids}
    for n in node_ids:
        for d in dict.fromkeys(depends_on.get(n, [])):
            if d in indeg:
                indeg[n] += 1
                children[d].append(n)
    ready = sorted(n for n, k in indeg.items() if k == 0)
    order: list[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for c in sorted(children[n]):
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
        ready.sort()
    if len(order) != len(node_ids):
        return None
    return order


FragmentIndex = dict[tuple[str, str], set[str]]  # (file_id, version) -> registered fragment ids (without '#')


def _fragment_known(index: FragmentIndex | None, file_id: str, version: str, fragment: str) -> bool:
    if index is None:
        return False
    return fragment in index.get((file_id, version), set())


def validate_graph(plan: dict[str, Any], registered_fragments: FragmentIndex | None = None) -> list[GraphError]:
    """``registered_fragments`` comes from the source registry (P02). Without one, only ``#root``
    is accepted — identical to P01R behaviour, so no-registry compiles are byte-stable."""
    out: list[GraphError] = []
    tasks: list[dict[str, Any]] = list(plan.get("tasks") or [])
    edges: list[dict[str, Any]] = list(plan.get("edges") or [])
    sources = plan.get("source_versions") or []

    # --- sources -----------------------------------------------------------------------
    scope_of: dict[tuple[str, str], str] = {}  # (file_id, version) -> "file_id@content_hash"
    seen_files: set[str] = set()
    for s in sources:
        if s["file_id"] in seen_files:
            out.append(GraphError(errors.DUPLICATE_SOURCE_ID, f"source_versions declares {s['file_id']!r} twice"))
        seen_files.add(s["file_id"])
        scope_of[(s["file_id"], s["version"])] = f"{s['file_id']}@{s['content_hash']}"
    known_scopes = set(scope_of.values())

    # --- node ids ----------------------------------------------------------------------
    ids = [t.get("node_id") for t in tasks]
    seen: set[str] = set()
    for nid in ids:
        if nid in seen:
            out.append(GraphError(errors.DUPLICATE_NODE_ID, f"duplicate node_id {nid!r}", nid))
        seen.add(nid)
    id_set = set(ids)
    dep_map = {t["node_id"]: list(t.get("depends_on") or []) for t in tasks}
    output_schema_by_node = {t.get("node_id"): t.get("output_schema_ref") for t in tasks}

    declared: Counter[EdgeKey] = Counter((e["from"], e["to"], e.get("binding_ref")) for e in edges)
    edge_pairs = {(f, t) for (f, t, _) in declared}

    # --- per node ----------------------------------------------------------------------
    for t in tasks:
        nid = t["node_id"]
        deps_list = dep_map[nid]
        if len(deps_list) != len(set(deps_list)):
            out.append(GraphError(errors.DEPENDS_ON_DUPLICATE, f"{nid} lists a dependency twice", nid))
        deps = set(deps_list)
        for d in sorted(deps):
            if d not in id_set:
                out.append(GraphError(errors.DANGLING_DEPENDENCY, f"{nid} depends on unknown node {d!r}", nid))
            elif (d, nid) not in edge_pairs:
                out.append(GraphError(errors.EDGE_DEPENDS_MISMATCH, f"depends_on {d}->{nid} has no matching edge", nid))
        if t.get("routing_class") == "zero_model" and ("model_policy" in t or "required_capabilities" in t):
            out.append(GraphError(errors.ZERO_MODEL_HAS_MODEL_POLICY, "zero_model node declares model fields", nid))

        aliases: set[str] = set()
        for b in t.get("input_bindings") or []:
            alias = b.get("bind_as")
            src = b.get("from_node")
            if alias in aliases:
                out.append(GraphError(errors.BINDING_DUPLICATE_ALIAS, f"duplicate bind_as {alias!r}", nid))
            aliases.add(alias)
            if not _OUTPUT_PATH.match(str(b.get("output_path", ""))):
                out.append(GraphError(errors.BINDING_PATH_INVALID, f"output_path {b.get('output_path')!r} not allowed", nid))
            if src not in deps:
                out.append(GraphError(errors.BINDING_DEPENDS_MISMATCH, f"binding from {src!r} not in depends_on", nid))
            if (src, nid, alias) not in declared:
                out.append(GraphError(errors.BINDING_UNAUTHORIZED, f"no edge authorizes binding {alias!r} from {src!r}", nid))
            if src in output_schema_by_node and b.get("schema_ref") != output_schema_by_node[src]:
                out.append(
                    GraphError(
                        errors.BINDING_SCHEMA_MISMATCH,
                        f"binding {alias!r} declares {b.get('schema_ref')!r} but {src} emits {output_schema_by_node[src]!r}",
                        nid,
                    )
                )

        # I3 — exact (file_id, version) binding; fragments must be registered
        scopes = set(t.get("source_scope") or [])
        for sc in sorted(scopes):
            if sc not in known_scopes:
                out.append(GraphError(errors.SOURCE_UNKNOWN, f"source_scope {sc!r} not in source_versions", nid))
        bound_scopes: set[str] = set()
        for fr in t.get("fragment_refs") or []:
            parsed = parse_fragment_ref(fr)
            if parsed is None:
                out.append(GraphError(errors.FRAGMENT_REF_MALFORMED, f"fragment ref {fr!r} is not <file_id>@<version>#<fragment>", nid))
                continue
            file_id, version, fragment = parsed
            scope = scope_of.get((file_id, version))
            if scope is None:
                out.append(GraphError(errors.FRAGMENT_VERSION_UNKNOWN, f"fragment {fr!r}: {file_id}@{version} is not a declared source version", nid))
                continue
            if fragment != ROOT_FRAGMENT and not _fragment_known(registered_fragments, file_id, version, fragment):
                out.append(GraphError(errors.FRAGMENT_NOT_REGISTERED, f"fragment {fr!r} is not registered for {file_id}@{version}", nid))
            if scope not in scopes:
                out.append(GraphError(errors.SOURCE_SCOPE_VIOLATION, f"fragment {fr!r} outside source_scope", nid))
            bound_scopes.add(scope)
        # F1 — source_scope is an upper authorization bound, never an input list: every scope
        # entry must be bound by at least one fragment ref (root-only templates: exact equality).
        for sc in sorted(scopes - bound_scopes):
            out.append(GraphError(errors.SOURCE_SCOPE_UNBOUND, f"source_scope {sc!r} is authorized but no fragment_ref binds it", nid))

    # --- edge set exactness (I4 / R2) -------------------------------------------------------
    exp = expected_edges(tasks)
    for key, n in sorted(declared.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or "")):
        frm, to, alias = key
        if n > 1:
            out.append(GraphError(errors.EDGE_DUPLICATE, f"edge {frm}->{to} ({alias or 'control'}) declared {n} times", to))
        if frm not in id_set or to not in id_set:
            out.append(GraphError(errors.DANGLING_DEPENDENCY, f"edge references unknown node {frm}->{to}"))
        elif frm not in dep_map[to]:
            out.append(GraphError(errors.EDGE_DEPENDS_MISMATCH, f"edge {frm}->{to} missing in depends_on", to))
        elif key not in exp:
            what = f"binding_ref {alias!r} has no matching input_binding" if alias else "control edge where bindings exist"
            out.append(GraphError(errors.EDGE_UNEXPECTED, f"edge {frm}->{to}: {what}", to))

    # --- order -----------------------------------------------------------------------------
    if not any(x.code == errors.DUPLICATE_NODE_ID for x in out):
        order = topological_order(ids, dep_map)
        if order is None:
            out.append(GraphError(errors.CYCLE_DETECTED, "dependency graph contains a cycle"))
        elif order != ids:
            out.append(GraphError(errors.TOPOLOGICAL_ORDER_UNSTABLE, f"tasks must be in canonical order {order}"))

    return out


def raise_if_invalid(plan: dict[str, Any], registered_fragments: FragmentIndex | None = None) -> None:
    problems = validate_graph(plan, registered_fragments)
    if problems:
        raise errors.DcsError(
            errors.PLAN_INVALID,
            "plan violates graph invariants",
            http_status=422,
            details=[p.to_dict() for p in problems],
        )
