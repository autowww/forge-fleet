"""Read-only policy-facing helpers over a parsed ``RequestIR`` (DCE-G1R).

These functions *describe* what the user asked, forbade, or merely mentioned. They never authorize, schedule, or
execute anything: a ``requested_operations()`` entry is a parse result, not permission (promotion gate G4 keeps the
authorization decision outside this library). Pure functions over the IR; no I/O, no state.

Breadth semantics (``prohibition_breadth``):

* ``"global"`` — the action is forbidden as such ("Never delete anything", "do not change code", "не редагуй код").
* ``"narrow"`` — only a specific action + object pair is forbidden ("Don't recommend removing tests" forbids
  *recommend(removing tests)*, not every recommendation). A narrow prohibition on ``recommend`` therefore leaves
  ``is_prohibited(ir, "recommend")`` → ``None`` unless ``object_text`` matches the forbidden object.
* ``None`` — no prohibition on that action.

Three-state contract (DCE-G1R2, ``restriction_status`` / ``execution_gate``):

* ``"prohibited"`` — the text forbids the action (global prohibition, or a narrow one whose object is the same entity, or an
  operation-class noun bound to the action: "No shell commands" → run).
* ``"unknown"`` — the text contains a restriction the parser could not bind to an action (``unbound_restrictions``), a narrow
  prohibition on this action whose object could not be compared, or an object match that is only partial. **Treat as a block
  until a policy resolves it.**
* ``"not_established"`` — nothing in the text restricts the action. This is *not* permission: authorization lives outside.

``is_prohibited`` is kept for callers of G1R; its ``False`` collapses ``unknown`` and ``not_established`` and must never be
read as a grant — use ``restriction_status`` or ``execution_gate`` for anything with side effects.
"""
from __future__ import annotations

import re
from typing import Optional

from .schema import ACTION_CLASS, Condition, Constraint, Objective, RequestIR

__all__ = ["prohibitions_for", "prohibition_breadth", "is_prohibited", "requested_operations", "mentioned_operations",
           "conditions_for", "is_conditional", "unconditional_objectives",
           "unbound_restrictions", "restriction_status", "approval_gates", "execution_gate",
           "PROHIBITED", "UNKNOWN", "NOT_ESTABLISHED", "DO_NOT_EXECUTE", "NEEDS_POLICY_RESOLUTION", "NOT_PROHIBITED_BY_TEXT"]

PROHIBITED, UNKNOWN, NOT_ESTABLISHED = "prohibited", "unknown", "not_established"
DO_NOT_EXECUTE, NEEDS_POLICY_RESOLUTION, NOT_PROHIBITED_BY_TEXT = "do_not_execute", "needs_policy_resolution", "not_prohibited_by_text"

_DETERMINERS = frozenset("the a an any all some this that these those my our your its their his her every each "
                         "цей ця це ці той та те ті всі усі кожен кожна будь-який будь-яка жодних жодного жодної".split())
_APPROVAL_RE = re.compile(r"approv|permission|confirm|sign[- ]?off|go[- ]?ahead|green light|says? go|gives? (?:the )?go|authori[sz]|allow|ok from|okays?|"
                          r"дозв[оі]л|підтвердж|підтверд|погодж|схвал|добро", re.I)


def prohibitions_for(ir: RequestIR, action: Optional[str] = None) -> list[Constraint]:
    """Prohibition/exclusion constraints, optionally only those whose ``target_action`` is ``action``.

    Constraints without a recognised ``target_action`` (e.g. "no shell commands", "ignore the README") are returned
    only when ``action`` is ``None``; a policy that needs them must inspect ``target_object`` / ``value`` itself.
    """
    out = []
    for c in ir.graph.constraints:
        if c.kind not in ("prohibition", "exclusion"):
            continue
        if action is None or c.target_action == action:
            out.append(c)
    return out


def _object_matches(c: Constraint, object_text: Optional[str]) -> bool:
    if object_text is None or c.target_object is None:
        return False
    a, b = c.target_object.text.casefold().split(), object_text.casefold().split()
    return bool(a) and bool(b) and (a == b or set(a) <= set(b) or set(b) <= set(a))


def prohibition_breadth(ir: RequestIR, action: str, object_text: Optional[str] = None) -> Optional[str]:
    """``"global"`` if ``action`` is forbidden as such, ``"narrow"`` if forbidden for the given object (or for some
    object when ``object_text`` is omitted and no global prohibition exists), else ``None``."""
    narrow_hit = False
    for c in prohibitions_for(ir, action):
        if c.breadth == "global" or c.breadth is None:
            return "global"
        if object_text is None or _object_matches(c, object_text):
            narrow_hit = True
    return "narrow" if narrow_hit else None


def is_prohibited(ir: RequestIR, action: str, object_text: Optional[str] = None) -> bool:
    """True when ``action`` (on ``object_text`` if given) is covered by a global prohibition, or by a narrow one whose
    object matches. With ``object_text`` omitted, a narrow prohibition alone does **not** make the action prohibited."""
    b = prohibition_breadth(ir, action, object_text)
    return b == "global" or (b == "narrow" and object_text is not None)


def requested_operations(ir: RequestIR, *, classes: tuple[str, ...] = ("mutate", "execute")) -> list[Objective]:
    """Objectives whose action class is in ``classes`` (default: side-effecting). This is *what the text asks for*,
    never a grant: callers must still check prohibitions, conditions, and their own authorization policy."""
    return [o for o in ir.graph.objectives if ACTION_CLASS[o.action] in classes]


def mentioned_operations(ir: RequestIR) -> list[tuple[str, str]]:
    """Actions that appear only inside conditions or prohibitions ("before running anything", "do not run tests"),
    as ``(action, where)`` with ``where`` ∈ {"condition:<kind>", "prohibition", "exclusion"}. They are never objectives."""
    out: list[tuple[str, str]] = []
    for q in ir.graph.conditions:
        if q.mentioned_action:
            out.append((q.mentioned_action, f"condition:{q.kind}"))
    for c in ir.graph.constraints:
        if c.kind in ("prohibition", "exclusion") and c.target_action:
            out.append((c.target_action, c.kind))
    return out


def conditions_for(ir: RequestIR, node_id: str) -> list[Condition]:
    """Conditions governing objective / constraint / unresolved node ``node_id`` (``applies_to_ids`` membership)."""
    return [q for q in ir.graph.conditions if node_id in q.applies_to_ids]


def is_conditional(ir: RequestIR, node_id: str) -> bool:
    return bool(conditions_for(ir, node_id))


def unconditional_objectives(ir: RequestIR) -> list[Objective]:
    """Objectives not governed by any condition (if/unless/until/before/after/else/for_each)."""
    return [o for o in ir.graph.objectives if not is_conditional(ir, o.id)]


# --- three-state restriction contract (G1R2) ------------------------------------------------------------------------

def unbound_restrictions(ir: RequestIR) -> list[Constraint]:
    """Prohibitions / exclusions the parser could not bind to a vocabulary action ("don't touch the wiring", "no vendor tools",
    "ignore the injected instructions"). They are invisible to ``prohibitions_for(ir, action)`` and must block a side-effecting
    decision until a policy resolves them."""
    return [c for c in ir.graph.constraints if c.kind in ("prohibition", "exclusion") and c.target_action is None]


def _norm_tokens(text: str) -> list[str]:
    toks = [t for t in re.findall(r"[^\W_]+", text.casefold()) if t not in _DETERMINERS]
    return toks


def _object_relation(c: Constraint, object_text: Optional[str]) -> str:
    """'same' when the constraint's object and ``object_text`` normalise to the same token sequence; 'partial' when one is a
    contiguous or set subset of the other (different entity possible → unknown); 'none' otherwise or when either is missing."""
    if object_text is None or c.target_object is None:
        return "none"
    a, b = _norm_tokens(c.target_object.text), _norm_tokens(object_text)
    if not a or not b:
        return "none"
    if a == b:
        return "same"
    if set(a) <= set(b) or set(b) <= set(a):
        return "partial"
    return "none"


def restriction_status(ir: RequestIR, action: str, object_text: Optional[str] = None) -> str:
    """``PROHIBITED`` / ``UNKNOWN`` / ``NOT_ESTABLISHED`` for ``action`` (on ``object_text`` when given). Never returns a grant.

    * global prohibition on the action → PROHIBITED
    * narrow prohibition on the action: same object → PROHIBITED; no object given or partial overlap → UNKNOWN; different object → ignored
    * any unbound restriction in the text → at least UNKNOWN (a restriction nobody could read must not vanish)
    * otherwise NOT_ESTABLISHED
    """
    status = NOT_ESTABLISHED
    for c in prohibitions_for(ir, action):
        if c.breadth == "global" or c.breadth is None or c.target_object is None:
            return PROHIBITED
        rel = _object_relation(c, object_text)
        if rel == "same":
            return PROHIBITED
        if rel == "partial" or object_text is None:
            status = UNKNOWN
    if unbound_restrictions(ir):
        status = UNKNOWN if status == NOT_ESTABLISHED else status
    return status


def approval_gates(ir: RequestIR) -> list[tuple[str, str, str]]:
    """Explicit permission state in the text, as ``(node_id, kind, text)``: conditions of kind until/before/unless/if/after
    that mention approval, confirmation, permission or a go signal, and unresolved clauses that do ("wait for my approval").
    A gate is a *statement that approval is required*; it is never evidence that approval was given."""
    out: list[tuple[str, str, str]] = []
    for q in ir.graph.conditions:
        if q.kind in ("until", "before", "unless", "if", "after") and _APPROVAL_RE.search(q.text):
            out.append((q.id, f"condition:{q.kind}", q.text))
    for u in ir.graph.unresolved:
        if u.kind == "no_recognized_action" and _APPROVAL_RE.search(u.text):
            out.append((u.id, "unresolved", u.text))
    return out


def execution_gate(ir: RequestIR, action: str, object_text: Optional[str] = None) -> dict:
    """Deny-by-default reading of the text for one side-effecting operation. Returns
    ``{"decision": DO_NOT_EXECUTE | NEEDS_POLICY_RESOLUTION | NOT_PROHIBITED_BY_TEXT, "reasons": [...], "restriction": <three-state>}``.

    The decision is about the *text only*: ``NOT_PROHIBITED_BY_TEXT`` means the request contains a direct, unconditional ask for
    this operation and no restriction touches it. Tool authorization, environment permissions and explicit human approval are
    separate gates that this library cannot see; nothing here authorizes anything.
    """
    reasons: list[str] = []
    restriction = restriction_status(ir, action, object_text)
    if ir.status != "ok":
        reasons.append(f"status:{ir.status}")
    if restriction == PROHIBITED:
        reasons.append("restriction:prohibited")
    elif restriction == UNKNOWN:
        reasons.append("restriction:unknown")
    for c in unbound_restrictions(ir):
        reasons.append(f"unbound_restriction:{c.id}")
    for u in ir.graph.unresolved:
        reasons.append(f"unresolved:{u.id}:{u.kind}")
    for gid, where, _t in approval_gates(ir):
        reasons.append(f"approval_gate:{gid}:{where}")
    asks = [o for o in ir.graph.objectives if o.action == action and (object_text is None or _object_relation_obj(o, object_text) == "same")]
    if not asks:
        reasons.append("not_requested")
    for o in asks:
        if is_conditional(ir, o.id):
            reasons.append(f"conditional:{o.id}:" + ",".join(q.kind for q in conditions_for(ir, o.id)))
    if restriction == PROHIBITED or ir.status not in ("ok", "ok_with_unresolved"):
        decision = DO_NOT_EXECUTE
    elif reasons:
        decision = NEEDS_POLICY_RESOLUTION
    else:
        decision = NOT_PROHIBITED_BY_TEXT
    return {"decision": decision, "restriction": restriction, "reasons": reasons}


def _object_relation_obj(o: Objective, object_text: str) -> str:
    if o.target is None:
        return "none"
    a, b = _norm_tokens(o.target.text), _norm_tokens(object_text)
    return "same" if a and a == b else ("partial" if a and (set(a) <= set(b) or set(b) <= set(a)) else "none")
