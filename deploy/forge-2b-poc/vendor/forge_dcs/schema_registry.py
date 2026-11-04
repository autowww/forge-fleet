"""Bundled, offline-only JSON Schema registry.

Every ``$ref`` must resolve to a schema shipped inside this package. Any attempt to resolve
an unknown URI raises :class:`DcsError` with ``SCHEMA_REF_UNRESOLVABLE``; no HTTP retrieval
path exists.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from forge_dcs import errors

PLANIR_ID = "urn:forge-dcs:schema:planir:v0.1"
NODE_CAPABILITY_ID = "urn:forge-dcs:schema:node_capability:v0.1"
EXECUTION_MANIFEST_ID = "urn:forge-dcs:schema:execution_manifest:v0.1"
PROMPT_ARTIFACT_ID = "urn:forge-dcs:schema:prompt_artifact:v0.1"

_BUNDLED_FILES = (
    "planir.v0.1.schema.json",
    "node_capability.v0.1.schema.json",
    "execution_manifest.v0.1.schema.json",
    "prompt_artifact.v0.1.schema.json",
)


def _deny_retrieve(uri: str):  # pragma: no cover - exercised via Unresolvable path
    raise errors.DcsError(
        errors.SCHEMA_REF_UNRESOLVABLE,
        f"schema reference is not bundled: {uri}",
        http_status=500,
    )


@lru_cache(maxsize=1)
def bundled_schemas() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    pkg = resources.files("forge_dcs").joinpath("schemas")
    for name in _BUNDLED_FILES:
        data = json.loads(pkg.joinpath(name).read_text(encoding="utf-8"))
        out[data["$id"]] = data
    return out


def build_registry(schemas: dict[str, dict[str, Any]]) -> Registry:
    """Offline registry over an explicit ``{uri: schema}`` map. Unknown URIs are denied, never fetched.

    Relative ``$ref`` values inside a schema resolve against that schema's ``$id`` (RFC 3986), so
    HTTPS-shaped ids are fine as *names* — nothing is retrieved from them.
    """
    reg: Registry = Registry(retrieve=_deny_retrieve)  # type: ignore[arg-type]
    for uri, schema in schemas.items():
        reg = reg.with_resource(uri, Resource.from_contents(schema, default_specification=DRAFT202012))
    return reg


@lru_cache(maxsize=1)
def registry() -> Registry:
    return build_registry(bundled_schemas())


@lru_cache(maxsize=8)
def validator_for(schema_id: str) -> Draft202012Validator:
    schemas = bundled_schemas()
    if schema_id not in schemas:
        raise errors.DcsError(errors.SCHEMA_REF_UNRESOLVABLE, f"unknown schema id: {schema_id}", http_status=500)
    schema = schemas[schema_id]
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry())


def validate_instance(schema_id: str, instance: Any) -> list[dict[str, Any]]:
    v = validator_for(schema_id)
    try:
        out = []
        for e in sorted(v.iter_errors(instance), key=lambda e: [str(p) for p in e.absolute_path]):
            out.append(
                {
                    "path": "/" + "/".join(str(p) for p in e.absolute_path),
                    "schema_path": "/" + "/".join(str(p) for p in e.absolute_schema_path),
                    "message": e.message,
                }
            )
        return out
    except Unresolvable as exc:
        raise errors.DcsError(errors.SCHEMA_REF_UNRESOLVABLE, f"unresolvable $ref: {exc}", http_status=500) from exc
    except Exception as exc:  # referencing wraps retrieval failures (e.g. _WrappedReferencingError)
        if "Unresolvable" in type(exc).__name__ or "Unresolvable" in str(exc):
            raise errors.DcsError(errors.SCHEMA_REF_UNRESOLVABLE, f"unresolvable $ref: {exc}", http_status=500) from exc
        raise


def assert_valid(schema_id: str, instance: Any) -> None:
    problems = validate_instance(schema_id, instance)
    if problems:
        raise errors.DcsError(errors.PLAN_SCHEMA_INVALID, "instance violates schema", http_status=422, details=problems)
