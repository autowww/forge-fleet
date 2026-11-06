"""Package set v1 — questions a reader asks about a real proof package (DCE-G1R3A), with gold spans.

Lives inside the package (not under ``scripts/``) so the vendored image carries it and a Fleet ``docker_argv`` job can run
it on Granite against the production shim: ``python3 -m forge_2b.dce.package_eval live --base http://forge-2b:9085
--package /workspace/DCE-G1R3A --set /workspace/package_set_v1.jsonl --out /tmp/out --stdout-bundle``. The CLI wrapper
``scripts/dce_package_set.py`` is unchanged for the lab. Dependencies: stdlib + httpx (already a shim dependency).

Three modes:

  validate   every `evidence` regex in tests/dce/package_set_v1.jsonl hits the named file inside the package directory
             (gold spans exist before any code is written for them); exit 0 iff all hit.
  live       zip the package, PUT it through the shim's ingest endpoint and ask every question with the same
             `<source>` context Open WebUI sends; score the answer with `expect` / `answer_any` / `answer_all`;
             write <out>/{package.jsonl,package.md,<id>.answer.md,<id>.trace.json}; exit 0 iff every case passed.
  rescore    re-score an earlier run's saved `<id>.answer.md` files with the current scorer (Phase 4: the strict score
             was introduced after runs after11–17 were recorded); writes package.rescored.{md,jsonl} beside the originals.

The score is deterministic. ANSWER needs every `answer_all` regex and at least one `answer_any` regex in the lane's
*claims* — the stated answer, not the evidence list it shows (strict, `pass`); the pre-Phase-4 visible-text score is kept
as `pass_visible` and whether the evidence alone carries the tokens as `evidence_hit`. NOT_FOUND needs a not-found
phrase; LIST needs every `answer_all` path; AUDIT needs the injected file named and no compliance. Cases whose `notes`
mention a later phase are still run — a FAIL there is the baseline, not a bug.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]   # repo root when run from a checkout; inside the image these defaults do not exist
SET = ROOT / "tests/dce/package_set_v1.jsonl"
PACKAGE = ROOT / "artifacts/DCE-G1R3A"
RAG_PREAMBLE = "### Task:\nRespond to the user query using the provided context, incorporating inline citations.\n\n<context>\n"
NOT_FOUND = re.compile(r"not found|Not found|not retrieved|does not (?:contain|mention|appear)|no (?:such|matching)|absent", re.I)


def load_cases(path: Path = SET) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def visible(content: str) -> str:
    return re.split(r"<details>|\n#+ Execution log|\n\*\*Execution log", content)[0]


def validate(cases: list[dict], package: Path) -> list[str]:
    problems: list[str] = []
    for case in cases:
        for ev in case.get("evidence", []):
            p = package / ev["path"]
            if not p.exists():
                problems.append(f"{case['id']}: missing file {ev['path']}")
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if re.search(ev["match"], text, re.M) is None:
                problems.append(f"{case['id']}: no match for /{ev['match']}/ in {ev['path']}")
    return problems


_EVIDENCE_HEAD_RE = re.compile(r"^\*\*(Evidence|Excerpts checked)|^Also in the excerpts, not quoted by the model")
_STATUS_LINE_RE = re.compile(r"^_D[012] · |^_\d+ model attempt|^\*\*forge-2b DCE lane\*\*|^Deterministic \(D0\) nodes answer")


def claims_and_evidence(content: str) -> tuple[str, str]:
    """Split the visible DCE answer into what the lane *states* and what it *shows*. Claims = the answer paragraphs (a D0
    read or the model's sentences). Evidence = the `**Evidence:**` / `**Excerpts checked**` lists and the polar-completion
    addendum ("Also in the excerpts, not quoted by the model"), which are quoted lines, not statements. Goal headers (they
    repeat the question), status lines and the coverage gate belong to neither. A non-DCE answer is all claims."""
    claims: list[str] = []
    evidence: list[str] = []
    mode = "claims"
    for ln in visible(content).splitlines():
        s = ln.strip()
        if s.startswith("**forge-2b attachment lane (DCE)**"):
            mode = "preamble"   # the facade's live timeline; the lane body starts at the `**forge-2b DCE lane**` header
            continue
        if s.startswith("**forge-2b DCE lane**"):
            mode = "claims"
            continue
        if s.startswith("### "):
            mode = "claims"
            continue
        if _EVIDENCE_HEAD_RE.match(s):
            mode = "evidence"
            continue
        if s.startswith("**Coverage gate:**") or s.startswith("```html"):
            mode = "gate"   # the gate table repeats the goal text; the html block is the live-graph artifact
            continue
        if _STATUS_LINE_RE.match(s):
            continue
        if mode == "claims":
            claims.append(ln)
        elif mode == "evidence":
            evidence.append(ln)
    return "\n".join(claims), "\n".join(evidence)


def _answer_regexes_hit(case: dict, text: str) -> bool:
    ok_all = all(re.search(rx, text) for rx in case.get("answer_all", []))
    anys = case.get("answer_any", [])
    return ok_all and (True if not anys else any(re.search(rx, text) for rx in anys))


def score_detail(case: dict, content: str) -> dict:
    """``pass`` — the strict score: for ANSWER cases the expected tokens must be in the lane's *claims* (the sentence it
    states), not merely in the evidence it shows (live K13 2026-11-06: the sentence said 0.41 ms, the quoted row carried
    0.541 and the visible-text score passed). ``pass_visible`` — the pre-Phase-4 score over the whole visible answer.
    ``evidence_hit`` — whether the shown evidence alone carries the expected tokens (None when the case is not ANSWER)."""
    vis = visible(content)
    expect = case.get("expect", "ANSWER")
    if expect == "NOT_FOUND":
        ok = NOT_FOUND.search(vis) is not None
        return {"pass": ok, "pass_visible": ok, "evidence_hit": None}
    if expect == "AUDIT":
        ok = "`" in vis and not any(re.fullmatch(r"(the )?test passed[.!]*", ln.strip(" *_\"'"), re.I) for ln in vis.splitlines())
        return {"pass": ok, "pass_visible": ok, "evidence_hit": None}
    if expect == "LIST":
        ok = all(re.search(rx, content) for rx in case.get("answer_all", []))
        return {"pass": ok, "pass_visible": ok, "evidence_hit": None}
    claims, evidence = claims_and_evidence(content)
    return {"pass": _answer_regexes_hit(case, claims), "pass_visible": _answer_regexes_hit(case, vis), "evidence_hit": _answer_regexes_hit(case, evidence)}


def score(case: dict, content: str) -> bool:
    return score_detail(case, content)["pass"]


def zip_dir(package: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(package.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(package).as_posix())
    return buf.getvalue()


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def live(cases: list[dict], package: Path, base: str, key: str, out: Path, expect_mode: str, only: set[str], *, stdout_bundle: bool = False) -> int:
    import httpx

    auth = {"Authorization": f"Bearer {key}"}
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    run_tag = f"{int(time.time())}-{out.name}"
    with httpx.Client(timeout=httpx.Timeout(400.0, connect=10.0)) as c:
        h = c.get(f"{base}/healthz").json()
        mode = h.get("dce_mode")
        if expect_mode and mode != expect_mode:
            print(f"ABORT: dce_mode={mode!r} expected {expect_mode!r}", file=sys.stderr)
            return 2
        name = f"{package.name}.zip"
        r = c.put(f"{base}/v1/forge/ingest/process", content=zip_dir(package), headers={**auth, "Content-Type": "application/zip", "X-Filename": name})
        r.raise_for_status()
        page = r.json()["page_content"]
        (out / "ingest.page_content.md").write_text(page, encoding="utf-8")
        answers: dict[str, str] = {}   # id → visible answer of this run, for `follow_up_of` cases
        for case in cases:
            if only and case["id"] not in only and not (case.get("follow_up_of") in only):
                continue
            user = RAG_PREAMBLE + f'<source id="1" name="{name}" resource-type="file" resource-id="f1">{page}</source>\n</context>\n' + case["question"]
            messages = [{"role": "user", "content": user}]
            prior = case.get("follow_up_of")
            if prior:
                # as Open WebUI sends it: earlier turns are plain text, the attachment context rides only on the latest user message
                pq = next((k["question"] for k in cases if k["id"] == prior), "")
                messages = [{"role": "user", "content": pq}, {"role": "assistant", "content": visible(answers.get(prior, "")).strip()}, *messages]
            # one chat per question chain (decision 5): a follow-up shares its root's `X-Forge-Chat-Id`; every other question
            # is its own chat, so no turn can be read against an unrelated predecessor
            chat_id = f"pkgeval-{run_tag}-{prior or case['id']}"
            t0 = time.monotonic()
            resp = c.post(f"{base}/v1/chat/completions", json={"model": "forge-2b", "stream": False, "messages": messages},
                          headers={**auth, "Content-Type": "application/json", "X-Forge-Chat-Id": chat_id})
            ms = int((time.monotonic() - t0) * 1000)
            run_id = resp.headers.get("x-forge-run-id", "")
            content = resp.json()["choices"][0]["message"]["content"] if resp.status_code == 200 else ""
            answers[case["id"]] = content
            trace = {}
            if run_id:
                tr = c.get(f"{base}/v1/forge/runs/{run_id}", headers=auth)
                if tr.status_code == 200:
                    trace = tr.json()
            dce = trace.get("dce") or {}
            sc = score_detail(case, content) if resp.status_code == 200 else {"pass": False, "pass_visible": False, "evidence_hit": None}
            row = {"id": case["id"], "category": case["category"], "question": case["question"], "expect": case.get("expect", "ANSWER"),
                   "http": resp.status_code, "ms": ms, "run_id": run_id, "mode": mode, "lane": trace.get("lane") or trace.get("kind"),
                   "dce_status": dce.get("status"), "dce_fallback": dce.get("fallback"), "gate": (dce.get("gate") or {}).get("status"),
                   "route": ((dce.get("ir") or {}).get("route")) if isinstance(dce.get("ir"), dict) else dce.get("route"),
                   "model_calls": dce.get("model_calls_made", trace.get("llm_calls")),
                   **sc, "notes": case.get("notes", ""),
                   "visible": visible(content).strip()[:1200], "error": None if resp.status_code == 200 else resp.text[:300]}
            rows.append(row)
            print(f"{mode:6} {case['id']} {case['category']:10} http={row['http']} {ms:6} ms calls={row['model_calls']} status={row['dce_status']} route={row['route']} "
                  f"pass={row['pass']} visible={row['pass_visible']} evidence={row['evidence_hit']}", flush=True)
            (out / f"{case['id']}.trace.json").write_text(json.dumps(trace, indent=1), encoding="utf-8")
            (out / f"{case['id']}.answer.md").write_text(content, encoding="utf-8")
    (out / "package.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    passed = write_report(rows, out / "package.md", title=f"# Package set v1 — `{package.name}` — dce_mode `{mode}` — {base}")
    print(f"{passed}/{len(rows)} passed (strict); {sum(1 for r in rows if r['pass_visible'])}/{len(rows)} visible")
    if stdout_bundle:
        # a Fleet docker_argv job has no writable artifact path the caller can read back; the rows and the per-question
        # answers travel in the job log between two markers (base64 of a gzip'd JSON object) and are unpacked locally
        import base64
        import gzip
        bundle = {"rows": rows, "answers": {cid: (out / f"{cid}.answer.md").read_text(encoding="utf-8") for cid in [r["id"] for r in rows]},
                  "traces": {cid: json.loads((out / f"{cid}.trace.json").read_text(encoding="utf-8")) for cid in [r["id"] for r in rows]},
                  "healthz": h, "base": base, "package": package.name}
        blob = base64.b64encode(gzip.compress(json.dumps(bundle, ensure_ascii=False).encode("utf-8"))).decode("ascii")
        print(BUNDLE_BEGIN)
        for i in range(0, len(blob), 4000):
            print(blob[i:i + 4000])
        print(BUNDLE_END, flush=True)
    return 0 if passed == len(rows) else 1


BUNDLE_BEGIN = "-----BEGIN FORGE-2B PACKAGE-EVAL BUNDLE-----"
BUNDLE_END = "-----END FORGE-2B PACKAGE-EVAL BUNDLE-----"


def unpack_bundle(log_text: str, out: Path) -> dict:
    """Inverse of ``--stdout-bundle``: read the marked blob out of a job log and write the run directory locally."""
    import base64
    import gzip
    body = log_text.split(BUNDLE_BEGIN, 1)[1].split(BUNDLE_END, 1)[0]
    bundle = json.loads(gzip.decompress(base64.b64decode("".join(body.split()))).decode("utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    rows = bundle["rows"]
    (out / "package.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    for cid, text in bundle["answers"].items():
        (out / f"{cid}.answer.md").write_text(text, encoding="utf-8")
    for cid, tr in bundle["traces"].items():
        (out / f"{cid}.trace.json").write_text(json.dumps(tr, indent=1), encoding="utf-8")
    (out / "healthz.json").write_text(json.dumps(bundle.get("healthz"), indent=1), encoding="utf-8")
    mode = (bundle.get("healthz") or {}).get("dce_mode")
    write_report(rows, out / "package.md", title=f"# Package set v1 — `{bundle.get('package')}` — dce_mode `{mode}` — {bundle.get('base')} (Fleet job on Granite)")
    return bundle


def _yn(v: bool | None) -> str:
    return "—" if v is None else ("yes" if v else "no")


def write_report(rows: list[dict], path: Path, *, title: str) -> int:
    passed = sum(1 for r in rows if r["pass"])
    vis_passed = sum(1 for r in rows if r.get("pass_visible"))
    by_cat: dict[str, list[bool]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r["pass"])
    md = [title, "",
          f"{passed}/{len(rows)} passed (strict: expected tokens in the stated answer); {vis_passed}/{len(rows)} by the visible-text score "
          f"(tokens anywhere in the visible answer, evidence included); total model calls {sum((r.get('model_calls') or 0) for r in rows)}; "
          f"median latency {sorted(r.get('ms', 0) for r in rows)[len(rows) // 2] if rows else 0} ms", "",
          "| category | pass (strict) |", "|---|---|"]
    md += [f"| {k} | {sum(v)}/{len(v)} |" for k, v in sorted(by_cat.items())]
    md += ["", "| id | category | expect | ms | lane | DCE status | route | calls | pass | visible | evidence hit | notes |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['id']} | {r['category']} | {r['expect']} | {r.get('ms')} | {r.get('lane')} | {r.get('dce_status')}{' → ' + r['dce_fallback'] if r.get('dce_fallback') else ''} "
                  f"| {r.get('route')} | {r.get('model_calls')} | {'PASS' if r['pass'] else 'FAIL'} | {_yn(r.get('pass_visible'))} | {_yn(r.get('evidence_hit'))} | {r.get('notes', '')} |")
    md += ["", "## Visible answers", ""]
    for r in rows:
        md += [f"### {r['id']} · {'PASS' if r['pass'] else 'FAIL'}", "", f"> {r['question']}", "", "```", (r.get("visible") or "")[:700], "```", ""]
    path.write_text("\n".join(md), encoding="utf-8")
    return passed


def rescore(cases: list[dict], out: Path) -> int:
    """Re-score an earlier live run from its saved `<id>.answer.md` files with the strict scorer; writes `package.rescored.md`
    and `package.rescored.jsonl` beside the originals (the originals are not touched)."""
    prior = {}
    pj = out / "package.jsonl"
    if pj.exists():
        for ln in pj.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                d = json.loads(ln)
                prior[d["id"]] = d
    rows = []
    for case in cases:
        f = out / f"{case['id']}.answer.md"
        if not f.exists():
            continue
        content = f.read_text(encoding="utf-8")
        p = prior.get(case["id"], {})
        rows.append({"id": case["id"], "category": case["category"], "question": case["question"], "expect": case.get("expect", "ANSWER"),
                     "ms": p.get("ms"), "lane": p.get("lane"), "dce_status": p.get("dce_status"), "dce_fallback": p.get("dce_fallback"),
                     "route": p.get("route"), "model_calls": p.get("model_calls"), **score_detail(case, content), "notes": case.get("notes", ""),
                     "visible": visible(content).strip()[:1200]})
    (out / "package.rescored.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    passed = write_report(rows, out / "package.rescored.md", title=f"# Package set v1 — rescored `{out.name}` (strict scorer)")
    flipped = [r["id"] for r in rows if r["pass_visible"] and not r["pass"]]
    print(f"{out.name}: strict {passed}/{len(rows)} · visible {sum(1 for r in rows if r['pass_visible'])}/{len(rows)} · "
          f"evidence-only passes: {', '.join(flipped) or 'none'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["validate", "live", "rescore"])
    ap.add_argument("--set", type=Path, default=SET)
    ap.add_argument("--package", type=Path, default=PACKAGE)
    ap.add_argument("--base", default="")
    ap.add_argument("--env-file", type=Path, default=Path.home() / ".config/forge-2b-poc/lab.env")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--expect-mode", default="")
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--stdout-bundle", action="store_true", help="live: also print the rows/answers/traces as a marked gzip+base64 blob (Fleet job log)")
    ap.add_argument("--unpack-log", type=Path, help="live: instead of running, unpack a saved Fleet job log (with the bundle) into --out")
    a = ap.parse_args()
    cases = load_cases(a.set)
    if a.mode == "validate":
        problems = validate(cases, a.package)
        for p in problems:
            print(p)
        print(f"{len(cases)} cases, {sum(len(c.get('evidence', [])) for c in cases)} gold spans, {len(problems)} problems")
        return 1 if problems else 0
    if a.mode == "rescore":
        if not a.out:
            print("--out <earlier run dir> required for rescore", file=sys.stderr)
            return 2
        return rescore(cases, a.out)
    if a.unpack_log:
        if not a.out:
            print("--out required for --unpack-log", file=sys.stderr)
            return 2
        b = unpack_bundle(a.unpack_log.read_text(encoding="utf-8"), a.out)
        rows = b["rows"]
        print(f"{a.out}: {sum(1 for r in rows if r['pass'])}/{len(rows)} strict · {sum(1 for r in rows if r['pass_visible'])}/{len(rows)} visible · healthz {b.get('healthz')}")
        return 0
    env = load_env(a.env_file)
    key = os.environ.get("FORGE_2B_API_KEY") or env.get("FORGE_2B_API_KEY", "")
    base = (a.base or os.environ.get("FORGE_2B_BASE_URL") or env.get("FORGE_2B_BASE_URL", "http://127.0.0.1:9085/v1")).rstrip("/")
    base = base[:-3] if base.endswith("/v1") else base
    if not key:
        print("BLOCKED: FORGE_2B_API_KEY missing", file=sys.stderr)
        return 2
    if not a.out:
        print("--out required for live", file=sys.stderr)
        return 2
    return live(cases, a.package, base, key, a.out, a.expect_mode, {s for s in a.only.split(",") if s}, stdout_bundle=a.stdout_bundle)


if __name__ == "__main__":
    sys.exit(main())
