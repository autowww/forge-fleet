"""CLI: ``dcs compile|validate|hash|ingest|sources|prompt``.

Output bytes of ``compile`` are identical to ``POST /v1/plans``; ``ingest`` / ``sources show`` /
``sources fragments`` emit the same canonical bodies as the corresponding HTTP routes. The
store root comes from ``DCS_STORE_ROOT`` (``--store-root`` overrides); when it is unset,
``compile`` behaves exactly as in P01 and the source commands fail with ``STORE_NOT_CONFIGURED``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from forge_dcs import __version__, errors
from forge_dcs.auth import AuthConfig, local_principal, resolve_tenant
from forge_dcs.canonical import canonical_bytes, plan_hash
from forge_dcs.compiler import compile_plan
from forge_dcs.contracts import CompileRequest
from forge_dcs.graph_validation import validate_graph
from forge_dcs.schema_registry import PLANIR_ID, validate_instance
from forge_dcs.store import SourceStore, StoreConfig


def _load_json(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _store_cfg(root: str | None) -> StoreConfig:
    return StoreConfig(root=Path(root)) if root else StoreConfig.from_env()


def compile_bytes(payload: dict[str, Any], auth_cfg: AuthConfig | None = None, store_cfg: StoreConfig | None = None) -> bytes:
    cfg = auth_cfg or AuthConfig.from_env()
    scfg = store_cfg or StoreConfig.from_env()
    principal = local_principal(cfg)
    try:
        req = CompileRequest.model_validate(payload)
    except ValidationError as exc:
        details = [{"path": "/" + "/".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        raise errors.DcsError(errors.REQUEST_INVALID, "request invalid", 422, details) from exc
    tenant = resolve_tenant(principal, req.tenant_id)
    registry: SourceStore | None = scfg.open() if scfg.root is not None else None
    return canonical_bytes(compile_plan(req, tenant, registry))


def _tenant(auth_cfg: AuthConfig | None = None) -> str:
    return local_principal(auth_cfg or AuthConfig.from_env()).tenant_id


def _emit(data: bytes, output: str | None) -> None:
    if output and output != "-":
        Path(output).write_bytes(data)
    else:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.write(b"\n")
        sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dcs", description="forge-dcs offline STRICT compiler")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compile", help="compile a request JSON into canonical PlanIR")
    c.add_argument("--input", required=True, help="request JSON path or - for stdin")
    c.add_argument("--output", help="write canonical bytes to file (default stdout)")
    c.add_argument("--store-root", help="override DCS_STORE_ROOT (registry check when set)")

    i = sub.add_parser("ingest", help="register an immutable source version (same body as POST /v1/sources)")
    i.add_argument("--file", required=True, help="path to the file bytes")
    i.add_argument("--file-id", required=True)
    i.add_argument("--mime", required=True, choices=["text/plain", "text/markdown", "application/json"])
    i.add_argument("--store-root")

    s = sub.add_parser("sources", help="read registered source metadata")
    ssub = s.add_subparsers(dest="scmd", required=True)
    for name in ("show", "fragments"):
        sp = ssub.add_parser(name)
        sp.add_argument("--file-id", required=True)
        sp.add_argument("--version", required=True)
        sp.add_argument("--store-root")

    pr = sub.add_parser("prompt", help="raw prompt custody (prompt_artifact.v0.1)")
    psub = pr.add_subparsers(dest="pcmd", required=True)
    preg = psub.add_parser("register", help="store the raw prompt bytes; prints the artifact record")
    preg.add_argument("--input", required=True, help="UTF-8 text file or - for stdin")
    preg.add_argument("--store-root")

    v = sub.add_parser("validate", help="schema + graph validation of a PlanIR JSON")
    v.add_argument("--input", required=True)

    h = sub.add_parser("hash", help="recompute plan_hash for a PlanIR JSON")
    h.add_argument("--input", required=True)

    args = p.parse_args(argv)
    try:
        if args.cmd == "compile":
            _emit(compile_bytes(_load_json(args.input), store_cfg=_store_cfg(args.store_root)), args.output)
            return 0
        if args.cmd == "ingest":
            store = _store_cfg(args.store_root).open()
            rec, created = store.ingest(_tenant(), args.file_id, args.mime, Path(args.file).read_bytes())
            _emit(canonical_bytes(rec.to_dict() | {"created": created}), None)
            return 0
        if args.cmd == "sources":
            store = _store_cfg(args.store_root).open()
            tenant = _tenant()
            rec = store.get_version(tenant, args.file_id, args.version)
            if rec is None:
                raise errors.DcsError(errors.SOURCE_NOT_FOUND, f"{args.file_id}@{args.version} not registered", http_status=404)
            if args.scmd == "show":
                _emit(canonical_bytes(rec.to_dict()), None)
            else:
                frags = [f.to_dict() for f in store.list_fragments(tenant, args.file_id, args.version)]
                _emit(canonical_bytes({"file_id": args.file_id, "version": args.version, "content_hash": rec.content_hash, "parser_id": rec.parser_id, "fragments": frags}), None)
            return 0
        if args.cmd == "prompt":
            store = _store_cfg(args.store_root).open()
            text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
            rec, created = store.register_prompt(_tenant(), text)
            _emit(canonical_bytes(rec.to_dict() | {"created": created}), None)
            return 0
        if args.cmd == "validate":
            plan = _load_json(args.input)
            problems = validate_instance(PLANIR_ID, plan)
            problems += [g.to_dict() for g in validate_graph(plan)]
            stored, computed = plan.get("plan_hash"), plan_hash(plan)
            if stored != computed:
                problems.append({"code": "PLAN_HASH_MISMATCH", "message": f"stored {stored} != computed {computed}"})
            print(json.dumps({"ok": not problems, "problems": problems}, indent=2))
            return 0 if not problems else 3
        if args.cmd == "hash":
            print(plan_hash(_load_json(args.input)))
            return 0
    except errors.DcsError as exc:
        sys.stderr.write(json.dumps(exc.to_body()) + "\n")
        return 2
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
