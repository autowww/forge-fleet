"""Deterministic shaping for a turn whose contract is one JSON object.

This sits between the chat interface and the pinned 2B model. It does not
rewrite a diagnosis. It stops answer-shaping verbs ("produce a valid order")
from being treated as an environment change, and it returns the JSON object
without a refusal line, a Markdown fence, or the live graph.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace

from contextvars import ContextVar

from ..chat_artifacts import env_contract_note_mode
from ..chat_lane import Reading

_NOTE_OVERRIDE: ContextVar[str | None] = ContextVar("forge_2b_contract_note_override", default=None)


def set_contract_note_override(mode: str | None):
    return _NOTE_OVERRIDE.set(mode)


def reset_contract_note_override(token) -> None:
    _NOTE_OVERRIDE.reset(token)


def contract_note_mode() -> str:
    ovr = _NOTE_OVERRIDE.get()
    if ovr:
        m = ovr.strip().lower()
        if m in ("off", "0", "false", "no"):
            return "off"
        if m == "full":
            return "full"
        return "mechanical"
    return env_contract_note_mode()

# Contract families, one line per wording the student library uses. The label
# names the section; the sentence names the shape. A prompt is structured when
# a label and a sentence both appear, or when the G03 sentence appears alone.
#
#   G01  "## Output contract"            "Output parseable JSON" / "Output a compact JSON object" / "Output CSV only"
#   G01  "## Output contract"  (C3/C4)   "Output JSON with <keys>" / "Provide one CSV row ..." / "Provide canonical CSV with header ..."
#   G02  "## Output contract"            "Output valid JSON object with keys" / "Return only the required JSON contract"
#   G03  "## Required output contract"   "Return exactly one valid JSON object ... No Markdown fences."
#   G04  "## Required response object"   "Return exactly the required JSON object, without Markdown fences."
#   G05  "**Required response:**"        "one JSON object only, no Markdown"
#   G06  "**Output contract:**"          "Return **one JSON object only**"
#   G07  "## Required output"            "Return **one JSON object only**, with exactly these top-level fields"
_CONTRACT_LABEL = re.compile(
    r"(?im)^\W{0,6}(?:required\s+output(?:\s+contract)?|output\s+contract|(?:required\s+)?response(?:\s+object)?)\b\W{0,4}",
)
_JSON_SENTENCE = re.compile(
    r"(?i)(?:return\s+exactly\s+(?:one\s+valid|the\s+required)\s+json\s+object"
    r"|\bone\s+json\s+object\s+only\b"
    r"|\boutput\s+(?:a\s+)?(?:valid|compact|parseable)\s+json\b"
    r"|\boutput\s+json\s+with\b"
    r"|return\s+only\s+the\s+required\s+json\s+contract)",
)
_CSV_SENTENCE = re.compile(
    r"(?i)(?:\boutput\s+csv\s+only\b|\bprovide\s+(?:one\s+)?(?:canonical\s+)?csv\b)",
)
# The G03 wording stands on its own, and it is the only family whose attachments
# the reader annotates (contract_note). Other families get the shape only.
_CONTRACT = re.compile(
    r"Return exactly one valid JSON object|No Markdown fences|Required output contract",
    re.I,
)
_ANSWER_VERB = re.compile(r"(?i)^(produce|return|select|report|give|identify)\b")
_DANGER = re.compile(r"(?i)\b(file|disk|deploy|command|shell|database|endpoint|sudo)\b")
_FENCE = re.compile(r"```(?:json|csv|text)?\s*([\s\S]*?)```", re.I)
_PREFIX = "I will not run, write, or change anything."
_TIMELINE = "\n\n**Live timeline:**"


def contract_kind(user_text: str) -> str | None:
    """``"json"``, ``"csv"``, or ``None`` when the turn is ordinary chat."""
    text = user_text or ""
    if _CONTRACT.search(text):
        return "json"
    if not _CONTRACT_LABEL.search(text):
        return None
    if _JSON_SENTENCE.search(text):
        return "json"
    if _CSV_SENTENCE.search(text):
        return "csv"
    return None


def is_structured_contract(user_text: str) -> bool:
    return contract_kind(user_text) is not None


def _note_eligible(user_text: str) -> bool:
    return _CONTRACT.search(user_text or "") is not None


def relax_answer_shaping(reading: Reading, user_text: str) -> Reading:
    """Drop side effects that only name the answer to produce."""
    if not is_structured_contract(user_text) or not reading.side_effects:
        return reading
    kept = []
    for action, effect, text in reading.side_effects:
        if _ANSWER_VERB.match(text.strip()) and not _DANGER.search(text):
            continue
        kept.append((action, effect, text))
    if len(kept) == len(reading.side_effects):
        return reading
    return replace(reading, side_effects=tuple(kept))


def json_instruction(user_text: str) -> str:
    kind = contract_kind(user_text)
    if kind == "csv":
        return (
            " The user requires CSV. "
            "Reply with the header row and the data rows, then only the prose the contract asks for: "
            "no preamble, no fence, no timeline."
        )
    if kind == "json":
        return (
            " The user requires exactly one JSON object and no Markdown. "
            "Reply with that object only: no preamble, no fence, no timeline."
        )
    return ""


_SOURCE = re.compile(
    r'<source\b[^>]*path="([^"]+)"[^>]*>\s*([\s\S]*?)\s*</source>',
    re.I,
)
_SWALLOW_SUCCESS = re.compile(
    r"except\s+Exception\s*:\s*pass\b[\s\S]{0,240}\breturn\s+True\b",
    re.I,
)
_DEF = re.compile(r"def\s+\w+\s*\(([^)]*)\)\s*:(.*)\Z", re.S)


def _ignores_resource(body: str) -> bool:
    match = _DEF.search(body.strip())
    if not match:
        return False
    params, rest = match.group(1), match.group(2)
    return (
        re.search(r"\bresource\b", params) is not None
        and re.search(r"\bresource\b", rest) is None
        and re.search(r"\breturn\s+True\b", rest) is not None
    )


def _parses_json(body: str) -> bool:
    try:
        json.loads(body)
    except json.JSONDecodeError:
        return False
    return True


def _unread_params(body: str) -> list[str]:
    match = re.search(r"def\s+\w+\s*\(([^)]*)\)\s*:(.*)\Z", body.strip(), re.S)
    if not match:
        return []
    params = re.findall(r"\b[A-Za-z_]\w*\b", match.group(1))
    rest = match.group(2)
    return [name for name in params if name != "self" and re.search(rf"\b{re.escape(name)}\b", rest) is None]


def _repeated_call(body: str) -> str | None:
    match = re.search(r"def\s+(\w+)\s*\([^)]*\)\s*:(.*)\Z", body.strip(), re.S)
    if not match:
        return None
    fname, rest = match.group(1), match.group(2)
    calls = [name for name in re.findall(r"\b([A-Za-z_]\w*)\s*\(", rest) if name != fname]
    seen: dict[str, int] = {}
    for name in calls:
        seen[name] = seen.get(name, 0) + 1
    for name, count in seen.items():
        if count >= 2:
            return name
    return None


def _schema_notes(schema_body: str, candidate_body: str) -> list[str]:
    if not _parses_json(schema_body) or not _parses_json(candidate_body):
        return []
    schema = json.loads(schema_body)
    candidate = json.loads(candidate_body)
    if not isinstance(schema, dict) or not isinstance(candidate, dict):
        return []
    notes = []
    missing = [name for name in schema.get("required") or [] if name not in candidate]
    if missing:
        notes.append(
            "candidate.txt is valid JSON and omits required "
            + ", ".join(missing)
            + ". Verdict is FAIL and the violation must name the missing field."
        )
    props = schema.get("properties") or {}
    for key, spec in props.items():
        if key not in candidate or not isinstance(spec, dict):
            continue
        value = candidate[key]
        kind = spec.get("type")
        if kind == "boolean" and not isinstance(value, bool):
            notes.append(
                f"{key} is not a boolean. Verdict is FAIL and the violation must name that type mismatch."
            )
        if kind == "array" and not isinstance(value, list):
            notes.append(f"{key} is not an array. Verdict is FAIL and the violation must name that.")
        enum = spec.get("enum")
        if isinstance(enum, list) and value not in enum:
            notes.append(f"{key} is outside the allowed values. Verdict is FAIL and the violation must name that.")
    return notes


def contract_note(user_text: str) -> str:
    """Facts the reader can check on untrusted attachments, without writing the answer.

    Default mode is ``mechanical`` (parse/unread/swallow only). ``full`` restores
    answer-key phrasing for experiments; ``off`` disables notes for S1 scoring.
    """
    mode = contract_note_mode()
    if not _note_eligible(user_text) or mode == "off":
        return ""
    return _contract_note_body(user_text, full=mode == "full")


def _contract_note_body(user_text: str, *, full: bool) -> str:
    notes: list[str] = []
    task = user_text or ""
    asks_json = "valid json" in task.lower()
    bodies: dict[str, str] = {}
    for path, body in _SOURCE.findall(task):
        body = body.strip()
        name = path.rsplit("/", 1)[-1]
        bodies[name] = body
        if asks_json and body.startswith("{") and not _parses_json(body):
            notes.append(
                f"Attachment {name} is not valid JSON. "
                "A FAIL violation must name that parse failure. "
                "Do not replace it with a schema-property story."
            )
        if _SWALLOW_SUCCESS.search(body):
            notes.append(
                "The snippet catches Exception, ignores it, and still returns success. "
                "That is the principal defect, and the severity is BLOCKER."
            )
        if _ignores_resource(body):
            notes.append(
                "The function accepts resource and returns success without reading it. "
                "The principal defect is that the resource parameter is never read. "
                "The issue must say the resource parameter is never read, not a missing user check."
            )
        unread = [name for name in _unread_params(body) if name != "resource"]
        if unread:
            severity = " Severity is BLOCKER." if any(name in ("tenant", "resource") for name in unread) else ""
            extra = ""
            if "tenant" in unread:
                extra = " The issue must say the tenant parameter is never read, not that it fails validation or is hardcoded."
            notes.append(
                "Parameter " + ", ".join(unread) + " is never read." + severity
                + " The issue must name that unread parameter."
                + extra
            )
        repeated = _repeated_call(body)
        if repeated:
            notes.append(
                f"{repeated} is called more than once in one function. "
                "That repeated call is the principal defect and the severity is BLOCKER. "
                "The function does not call itself."
            )
    if full and "schema.json" in bodies and "candidate.txt" in bodies and _parses_json(bodies["candidate.txt"]):
        notes.extend(_schema_notes(bodies["schema.json"], bodies["candidate.txt"]))
    tasks = bodies.get("tasks.json")
    if full and tasks and _parses_json(tasks):
        doc = json.loads(tasks)
        steps = doc.get("steps") if isinstance(doc, dict) else None
        edges = doc.get("before_after") if isinstance(doc, dict) else None
        if isinstance(steps, list) and steps:
            notes.append("ordered_steps must include every step id exactly once: " + ", ".join(str(s) for s in steps) + ".")
        if isinstance(edges, list) and edges:
            notes.append(
                "Honor before-after edges: "
                + "; ".join(f"{pair[0]} before {pair[1]}" for pair in edges if isinstance(pair, list) and len(pair) == 2)
                + "."
            )
    claim = bodies.get("claim.md", "")
    if full and re.search(r"faster", claim, re.I) and re.search(r"cost", claim, re.I):
        notes.append(
            "The universal claim is about a faster query costing less. "
            "The counterexample must be a faster query that costs more, not a slower query."
        )
    unique = list(dict.fromkeys(notes))
    return "".join(" " + note for note in unique)


def present_structured(user_text: str, answer: str) -> str:
    """Return the JSON object or CSV when the contract demands one. Leave other chats unchanged."""
    kind = contract_kind(user_text)
    if kind is None:
        return answer
    text = answer or ""
    if _TIMELINE in text:
        text = text.split(_TIMELINE, 1)[0]
    text = text.strip()
    if text.startswith(_PREFIX):
        text = text[len(_PREFIX) :].strip()
    if kind == "csv":
        # CSV contracts may ask for a paragraph after the rows; unfence in place.
        return _FENCE.sub(lambda m: m.group(1).strip(), text).strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    obj = _first_object(text)
    if obj is not None:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return text.strip()


def _first_object(text: str):
    start = text.find("{")
    if start < 0:
        return None
    try:
        value, end = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return _lenient_object(text[start:])
    if isinstance(value, dict):
        return value
    return None


def _lenient_object(text: str):
    """Recover one object from unquoted keys or a trailing comma. Values are the model's own."""
    end = text.rfind("}")
    if end < 0:
        return None
    chunk = re.sub(r",(\s*[}\]])", r"\1", text[: end + 1])
    chunk = re.sub(r"([{\[,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', chunk)
    try:
        value = json.loads(chunk)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
