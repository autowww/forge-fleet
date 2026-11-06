"""Deterministic Comprehension Engine (DCE) — library only; not wired into the facade (DCE-01..03).

Public API: ``parse_request(text, attached_refs=None) -> RequestIR`` (see ``parse.py``), ``RequestIR`` (``ir.py``).
No LLM, embeddings, or network. Attachment *names* may be passed in to resolve mentions; content never enters here.
"""
from .ir import IR_VERSION, SCHEMA, AttachmentRef, RequestIR, prompt_hash
from .parse import parse_request

__all__ = ["parse_request", "RequestIR", "AttachmentRef", "IR_VERSION", "SCHEMA", "prompt_hash"]
