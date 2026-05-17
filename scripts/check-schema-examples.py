#!/usr/bin/env python3
"""Validate JSON example payloads under docs/examples/payloads/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VALID_DIR = REPO / "docs" / "examples" / "payloads" / "valid"
INVALID_DIR = REPO / "docs" / "examples" / "payloads" / "invalid"
SCHEMA_DIR = REPO / "docs" / "schemas"


def main() -> int:
    try:
        import jsonschema
    except ImportError:
        print("check-schema-examples: SKIP (install jsonschema for CI)", file=sys.stderr)
        return 0

    failures = 0
    if not VALID_DIR.is_dir():
        print(f"check-schema-examples: missing {VALID_DIR}", file=sys.stderr)
        return 1

    for js_path in sorted(VALID_DIR.glob("*.json")):
        schema_path = SCHEMA_DIR / f"{js_path.stem}.schema.json"
        if not schema_path.is_file():
            print(
                f"check-schema-examples: expected schema {schema_path.name} for {js_path.name}",
                file=sys.stderr,
            )
            failures += 1
            continue
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = json.loads(js_path.read_text(encoding="utf-8"))
        validator_cls = jsonschema.validators.validator_for(schema)
        validator = validator_cls(schema)
        try:
            validator.validate(payload)
        except jsonschema.ValidationError as exc:
            rel = js_path.relative_to(REPO)
            print(f"check-schema-examples: {rel}: {exc.message}", file=sys.stderr)
            failures += 1

    if INVALID_DIR.is_dir():
        for js_path in sorted(INVALID_DIR.glob("*.json")):
            marker = ".invalid."
            if marker not in js_path.name:
                print(
                    f"check-schema-examples: {js_path.relative_to(REPO)}: "
                    f"filename must contain {marker!r} (e.g. job-create-request.invalid.foo.json)",
                    file=sys.stderr,
                )
                failures += 1
                continue
            base = js_path.name.split(marker, 1)[0]
            schema_path = SCHEMA_DIR / f"{base}.schema.json"
            if not schema_path.is_file():
                print(
                    f"check-schema-examples: missing schema for {js_path.name} -> {schema_path.name}",
                    file=sys.stderr,
                )
                failures += 1
                continue
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            payload = json.loads(js_path.read_text(encoding="utf-8"))
            validator_cls = jsonschema.validators.validator_for(schema)
            validator = validator_cls(schema)
            try:
                validator.validate(payload)
            except jsonschema.ValidationError:
                pass
            else:
                print(
                    f"check-schema-examples: {js_path.relative_to(REPO)}: "
                    f"expected validation failure against {schema_path.name}",
                    file=sys.stderr,
                )
                failures += 1

    if failures:
        print(f"check-schema-examples: {failures} issue(s)", file=sys.stderr)
        return 1
    print("check-schema-examples: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
