"""Typed API/CLI request contract. Tenant identity is NEVER trusted from this body alone."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FILE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
CONTENT_HASH_PATTERN = r"^sha256:[a-f0-9]{64}$"
MAX_FILE_REFS = 8
MAX_PROMPT_CHARS = 4000


class FileRef(BaseModel):
    """Immutable reference to an already-registered source version.

    P01 does not ingest files; references are opaque identifiers plus a content hash.
    Paths, URLs and traversal sequences are rejected by the identifier pattern.
    """

    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(pattern=FILE_ID_PATTERN)
    version: str = Field(pattern=VERSION_PATTERN)
    content_hash: str = Field(pattern=CONTENT_HASH_PATTERN)

    @field_validator("file_id", "version")
    @classmethod
    def _no_traversal(cls, v: str) -> str:
        if ".." in v or "/" in v or "\\" in v or ":" in v:
            raise ValueError("path-like or traversal sequences are not permitted")
        return v


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    mode: Literal["STRICT"] = "STRICT"
    file_refs: list[FileRef] = Field(default_factory=list, max_length=MAX_FILE_REFS)
    tenant_id: str | None = Field(default=None, max_length=64)
    requested_fields: list[str] = Field(default_factory=list, max_length=32)
    comparison_dimension: str | None = Field(default=None, max_length=200)
    max_context_tokens_per_task: int = Field(default=2048, ge=256, le=32768)

    @field_validator("requested_fields")
    @classmethod
    def _fields_shape(cls, v: list[str]) -> list[str]:
        for f in v:
            if not f or len(f) > 64 or not f.replace("_", "").replace("-", "").isalnum():
                raise ValueError("requested_fields entries must be short identifiers")
        if len(set(v)) != len(v):
            raise ValueError("requested_fields must be unique")
        return v

    @field_validator("file_refs")
    @classmethod
    def _unique_sources(cls, v: list[FileRef]) -> list[FileRef]:
        keys = [(f.file_id, f.version) for f in v]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate file_id/version in file_refs")
        return v
