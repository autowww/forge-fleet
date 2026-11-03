"""Resolve catalog task_id from explicit headers/body, legacy mode, or rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from control_plane.modes import ALL_MODES, ModeId, normalize_mode

TaskSource = Literal[
    "header_task",
    "body_task",
    "header_mode",
    "body_mode",
    "path",
    "rules",
    "default",
]

MODE_TO_TASK: dict[ModeId, str] = {
    "interactive": "chat",
    "task_code": "code_generate",
    "struct_json": "json",
    "reason_short": "reason_simple",
    "long_ctx": "long_docs",
    "codegen_loop": "code_repo",
    "embed": "embedding",
    "batch_eval": "chat",
}

TASK_TO_MODE: dict[str, ModeId] = {v: k for k, v in MODE_TO_TASK.items()}
TASK_TO_MODE["embedding"] = "embed"

UNSUPPORTED_TASK_IDS = frozenset(
    {
        "ocr",
        "charts",
        "screenshot",
        "video_understand",
        "asr",
        "align",
        "tts",
        "speech_translate",
        "image",
        "image_edit",
        "video_gen",
        "video_edit",
        "forecast",
        "qlora",
        "multimodal_search",
    }
)

KNOWN_TASK_IDS: frozenset[str] | None = None


def _known_tasks() -> frozenset[str]:
    global KNOWN_TASK_IDS
    if KNOWN_TASK_IDS is not None:
        return KNOWN_TASK_IDS
    try:
        from control_plane.catalog_select import load_catalog

        cat = load_catalog()
        KNOWN_TASK_IDS = frozenset(t["task_id"] for t in cat.get("tasks", []))
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        KNOWN_TASK_IDS = frozenset(MODE_TO_TASK.values()) | frozenset(
            {
                "intent",
                "classification",
                "ner",
                "finance_facts",
                "entity_link",
                "guard",
                "hybrid",
                "rerank",
                "code_search",
                "summary",
                "translation",
                "reason_deep",
                "agent",
                "planner",
                "code_complete",
                "code_review",
                "testgen",
            }
        )
    return KNOWN_TASK_IDS


@dataclass(frozen=True)
class TaskResolution:
    task_id: str
    mode: ModeId
    source: TaskSource


def _normalize_task(raw: str | None) -> str | None:
    if not raw:
        return None
    t = raw.strip().lower().replace("-", "_")
    if t == "embed":
        return "embedding"
    return t


def resolve_task(
    *,
    header_task: str | None,
    body_task: str | None,
    header_mode: ModeId | None,
    body_mode: str | None,
    path: str,
    body: dict[str, Any] | None,
) -> TaskResolution:
    ht = _normalize_task(header_task)
    if ht:
        if ht not in _known_tasks() and ht not in UNSUPPORTED_TASK_IDS:
            raise ValueError(f"unknown task: {ht}")
        mode = TASK_TO_MODE.get(ht, "interactive")
        return TaskResolution(ht, mode, "header_task")

    bt = _normalize_task(body_task)
    if bt:
        if bt not in _known_tasks() and bt not in UNSUPPORTED_TASK_IDS:
            raise ValueError(f"unknown task: {bt}")
        mode = TASK_TO_MODE.get(bt, "interactive")
        return TaskResolution(bt, mode, "body_task")

    if header_mode:
        task = MODE_TO_TASK.get(header_mode, "chat")
        return TaskResolution(task, header_mode, "header_mode")

    bm = normalize_mode(body_mode)
    if bm:
        task = MODE_TO_TASK.get(bm, "chat")
        return TaskResolution(task, bm, "body_mode")

    if "/embeddings" in path:
        return TaskResolution("embedding", "embed", "path")

    if not body:
        return TaskResolution("chat", "interactive", "default")

    if body.get("response_format") or body.get("response_format") == {"type": "json_object"}:
        return TaskResolution("json", "struct_json", "rules")

    if body.get("tools"):
        return TaskResolution("agent", "reason_short", "rules")

    messages = body.get("messages") or []
    text = " ".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
    if len(text) > 12000:
        return TaskResolution("long_docs", "long_ctx", "rules")
    if any(k in text.lower() for k in ("def ", "class ", "pytest", "import ", "fix the bug")):
        return TaskResolution("code_generate", "task_code", "rules")
    if any(k in text.lower() for k in ("pdf", "extractor", "structure_discover", "synthesize")):
        return TaskResolution("code_repo", "codegen_loop", "rules")

    return TaskResolution("chat", "interactive", "default")


def assert_task_supported(task_id: str) -> None:
    if task_id in UNSUPPORTED_TASK_IDS:
        raise ValueError(
            f"task {task_id!r} requires a dedicated pipeline; not served on chat/embeddings routes"
        )
