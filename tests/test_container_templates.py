"""Requirement templates, fingerprinting, and docker argv injection."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from fleet_server import container_layout as cl
from fleet_server import container_templates as ct


def test_ensure_layout_creates_template_sidecar_files(tmp_path: Path) -> None:
    cl.ensure_layout(tmp_path)
    assert ct.requirement_templates_file(tmp_path).is_file()
    assert ct.build_cache_file(tmp_path).is_file()
    assert (ct.dockerfiles_allow_root(tmp_path) / "dockerfiles").is_dir()


def test_ensure_layout_seeds_certificator_source_ingest_template(tmp_path: Path) -> None:
    cl.ensure_layout(tmp_path)
    doc = ct.load_requirement_templates(tmp_path)
    rows = [t for t in (doc.get("templates") or []) if isinstance(t, dict)]
    ids = {str(t.get("id")) for t in rows}
    assert ct.BUILTIN_CERTIFICATOR_SOURCE_INGEST_TEMPLATE_ID in ids
    ref = f"dockerfiles/{ct.BUILTIN_CERTIFICATOR_SOURCE_INGEST_TEMPLATE_ID}/Dockerfile"
    for t in rows:
        if str(t.get("id")) == ct.BUILTIN_CERTIFICATOR_SOURCE_INGEST_TEMPLATE_ID:
            assert t.get("kind") == "dockerfile"
            assert t.get("ref") == ref
            p = ct._safe_ref_path(tmp_path, str(t.get("ref")))
            assert p.is_file()
            worker = p.parent / "fleet_source_ingest_worker.py"
            assert worker.is_file()
            break
    else:  # pragma: no cover
        raise AssertionError("builtin template row missing")


def test_seed_resyncs_deprecated_builtin_source_ingest_dockerfile(tmp_path: Path) -> None:
    """Stale on-disk Dockerfile from the git-based pip era must be replaced on ensure_layout."""
    cl.ensure_layout(tmp_path)
    ref = f"dockerfiles/{ct.BUILTIN_CERTIFICATOR_SOURCE_INGEST_TEMPLATE_ID}/Dockerfile"
    p = ct._safe_ref_path(tmp_path, ref)
    stale = (
        "FROM python:3.12-slim-bookworm\n"
        'RUN pip install "forge-certificators[prepcast] @ '
        "git+https://github.com/autowww/forge-certificators.git@${FORGE_CERTIFICATORS_GIT_REF}\"\n"
    )
    p.write_text(stale, encoding="utf-8")
    cl.ensure_layout(tmp_path)
    body = p.read_text(encoding="utf-8")
    assert "FORGE_CERTIFICATORS_GIT_REF" not in body
    assert "git+https://github.com/autowww/forge-certificators" not in body
    assert "fleet_source_ingest_worker.py" in body


def test_seed_resyncs_on_bundled_dockerfile_hash_mismatch(tmp_path: Path) -> None:
    cl.ensure_layout(tmp_path)
    ref = f"dockerfiles/{ct.BUILTIN_CERTIFICATOR_SOURCE_INGEST_TEMPLATE_ID}/Dockerfile"
    p = ct._safe_ref_path(tmp_path, ref)
    original = p.read_text(encoding="utf-8")
    p.write_text(original + "\n# operator-touched\n", encoding="utf-8")
    cl.ensure_layout(tmp_path)
    assert p.read_text(encoding="utf-8") == original


def test_bundle_fingerprint_stable_for_image_pin(tmp_path: Path) -> None:
    ct.ensure_template_layout(tmp_path)
    doc = ct.load_requirement_templates(tmp_path)
    doc["templates"] = [
        {"id": "base_alpine", "title": "Alpine pin", "kind": "image", "ref": "alpine:3.20", "notes": ""},
    ]
    ct.save_requirement_templates(tmp_path, doc)
    k1, fp1 = ct.bundle_fingerprint(tmp_path, ["base_alpine"])
    k2, fp2 = ct.bundle_fingerprint(tmp_path, ["base_alpine"])
    assert k1 == k2 and fp1 == fp2


def test_validate_template_row_accepts_hyphenated_image_tag(tmp_path: Path) -> None:
    ct.ensure_template_layout(tmp_path)
    row = ct.validate_template_row(
        tmp_path,
        {
            "id": "pw",
            "title": "PW",
            "kind": "image",
            "ref": "mcr.microsoft.com/playwright:v1.40.0-focal",
            "notes": "",
            "image_semver": "1.40.0",
        },
    )
    assert row["ref"].endswith("focal")
    assert row["image_semver"] == "1.40.0"


def test_validate_template_row_rejects_bad_image_semver(tmp_path: Path) -> None:
    ct.ensure_template_layout(tmp_path)
    with pytest.raises(ValueError, match="image_semver_invalid"):
        ct.validate_template_row(
            tmp_path,
            {
                "id": "x",
                "title": "X",
                "kind": "image",
                "ref": "alpine:3.20",
                "notes": "",
                "image_semver": "1.0 bad",
            },
        )


def test_validate_template_row_rejects_image_semver_on_dockerfile_kind(tmp_path: Path) -> None:
    ct.ensure_template_layout(tmp_path)
    root = ct.dockerfiles_allow_root(tmp_path)
    df = root / "dockerfiles" / "t.df"
    df.parent.mkdir(parents=True, exist_ok=True)
    df.write_text("FROM scratch\n", encoding="utf-8")
    with pytest.raises(ValueError, match="image_semver_only_for_image_kind"):
        ct.validate_template_row(
            tmp_path,
            {
                "id": "dfrow",
                "title": "D",
                "kind": "dockerfile",
                "ref": "dockerfiles/t.df",
                "notes": "",
                "image_semver": "1.0.0",
            },
        )


def test_bundle_fingerprint_includes_image_semver(tmp_path: Path) -> None:
    ct.ensure_template_layout(tmp_path)
    doc = ct.load_requirement_templates(tmp_path)
    doc["templates"] = [
        {"id": "v1", "title": "V", "kind": "image", "ref": "alpine:3.20", "notes": "", "image_semver": "1.0.0"},
    ]
    ct.save_requirement_templates(tmp_path, doc)
    k1, fp1 = ct.bundle_fingerprint(tmp_path, ["v1"])
    doc["templates"][0]["image_semver"] = "2.0.0"
    ct.save_requirement_templates(tmp_path, doc)
    k2, fp2 = ct.bundle_fingerprint(tmp_path, ["v1"])
    assert fp1 != fp2 and k1 != k2


def test_validate_types_unknown_requirement_raises(tmp_path: Path) -> None:
    cl.ensure_layout(tmp_path)
    doc = cl.load_types(tmp_path)
    doc["types"].append(
        {
            "id": "needs_fake",
            "category_id": "job",
            "container_class": "needs_fake",
            "title": "x",
            "requirements": ["not_declared_yet"],
        }
    )
    with pytest.raises(ValueError, match="unknown_requirement"):
        cl.validate_types_document(tmp_path, doc)


def test_inject_template_image_replaces_run_image_token() -> None:
    argv = ["docker", "run", "--rm", "-e", "FOO=1", "old:image", "echo", "hi"]
    out = ct.inject_template_image_into_docker_argv(argv, "new:image")
    assert out is argv
    assert "new:image" in argv
    assert "old:image" not in argv


def test_inject_template_image_accepts_docker_binary_path() -> None:
    argv = ["/usr/bin/docker", "run", "old:image", "echo", "hi"]
    ct.inject_template_image_into_docker_argv(argv, "fleet:tag")
    assert argv[2] == "fleet:tag"


def test_inject_template_image_docker_container_run() -> None:
    argv = ["docker", "container", "run", "old:image", "sh", "-c", "true"]
    ct.inject_template_image_into_docker_argv(argv, "new:image")
    assert argv[3] == "new:image"


def test_parse_build_if_missing_query_defaults_true() -> None:
    assert ct.parse_build_if_missing_query({}) is True
    assert ct.parse_build_if_missing_query({"build_if_missing": []}) is True
    assert ct.parse_build_if_missing_query({"build_if_missing": ["1"]}) is True
    assert ct.parse_build_if_missing_query({"build_if_missing": ["0"]}) is False
    assert ct.parse_build_if_missing_query({"build_if_missing": ["FALSE"]}) is False
    assert ct.parse_build_if_missing_query({"build_if_missing": ["no"]}) is False


def test_meta_build_template_if_missing_defaults_true() -> None:
    assert ct.meta_build_template_if_missing({}) is True
    assert ct.meta_build_template_if_missing({"build_template_if_missing": True}) is True
    assert ct.meta_build_template_if_missing({"build_template_if_missing": "yes"}) is True
    assert ct.meta_build_template_if_missing({"build_template_if_missing": False}) is False
    assert ct.meta_build_template_if_missing({"build_template_if_missing": 0}) is False
    assert ct.meta_build_template_if_missing({"build_template_if_missing": "no"}) is False


def test_template_build_network_opt_out(monkeypatch) -> None:
    monkeypatch.delenv("FLEET_TEMPLATE_BUILD_NETWORK", raising=False)
    assert ct._template_build_network_allowed() is True  # noqa: SLF001
    monkeypatch.setenv("FLEET_TEMPLATE_BUILD_NETWORK", "1")
    assert ct._template_build_network_allowed() is True  # noqa: SLF001
    monkeypatch.setenv("FLEET_TEMPLATE_BUILD_NETWORK", "0")
    assert ct._template_build_network_allowed() is False  # noqa: SLF001


def test_prefetch_requirement_template_images_calls_build_per_template(tmp_path: Path, monkeypatch) -> None:
    ct.ensure_template_layout(tmp_path)
    doc = ct.load_requirement_templates(tmp_path)
    doc["templates"] = [{"id": "a", "title": "A", "kind": "image", "ref": "img:a", "notes": ""}]
    ct.save_requirement_templates(tmp_path, doc)
    calls: list[list[str]] = []

    def fake_build(dd: Path, ids: list[str]) -> dict:
        calls.append(ids)
        assert dd == tmp_path
        return {"ok": True, "image": "x"}

    monkeypatch.setattr(ct, "run_template_build", fake_build)
    ct.prefetch_requirement_template_images(tmp_path)
    assert any(c == ["a"] for c in calls)


def test_prefetch_template_images_enabled_opt_out(monkeypatch) -> None:
    monkeypatch.delenv("FLEET_PREFETCH_TEMPLATE_IMAGES", raising=False)
    assert ct.prefetch_template_images_enabled() is True
    monkeypatch.setenv("FLEET_PREFETCH_TEMPLATE_IMAGES", "0")
    assert ct.prefetch_template_images_enabled() is False


def test_stderr_suggests_missing_buildx_detects_docker_message() -> None:
    err = (
        "ERROR: BuildKit is enabled but the buildx component is missing or broken.\n"
        "Install the buildx component to build images with BuildKit:\n"
    )
    assert ct._stderr_suggests_missing_buildx(err, "") is True  # noqa: SLF001


def test_stderr_suggests_missing_buildx_negative() -> None:
    assert ct._stderr_suggests_missing_buildx("no space left on device", "") is False  # noqa: SLF001


def test_run_template_build_retries_without_buildkit_on_buildx_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FLEET_DOCKER_BUILDKIT", raising=False)
    ct.ensure_template_layout(tmp_path)
    root = ct.dockerfiles_allow_root(tmp_path)
    df = root / "dockerfiles" / "tiny.df"
    df.parent.mkdir(parents=True, exist_ok=True)
    df.write_text("FROM alpine:3.20\nRUN echo hi\n", encoding="utf-8")
    doc = ct.load_requirement_templates(tmp_path)
    doc["templates"] = [
        {"id": "t1", "title": "T", "kind": "dockerfile", "ref": "dockerfiles/tiny.df", "notes": ""},
    ]
    ct.save_requirement_templates(tmp_path, doc)

    buildkit_flags: list[bool] = []

    def fake_run(cmd: list, *, capture_output: bool, text: bool, timeout: float, env: dict):  # noqa: ARG001
        bk = str(env.get("DOCKER_BUILDKIT", "0")) == "1"
        buildkit_flags.append(bk)
        if bk:
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout="",
                stderr="ERROR: BuildKit is enabled but the buildx component is missing or broken.\n",
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = ct.run_template_build(tmp_path, ["t1"])
    assert out.get("ok") is True
    assert buildkit_flags == [True, False]


def test_types_crud_add_and_delete_roundtrip(tmp_path: Path) -> None:
    from fleet_server import store

    cl.ensure_layout(tmp_path)
    db = tmp_path / "t.sqlite"
    conn = store.connect(db)
    try:
        added = cl.add_type_row(
            tmp_path,
            {
                "id": "tmp_probe",
                "category_id": "job",
                "container_class": "tmp_probe",
                "title": "Tmp",
                "notes": "",
            },
        )
        assert added["id"] == "tmp_probe"
        ok, detail = cl.delete_type_row(tmp_path, "tmp_probe", conn)
        assert ok is True and detail == "removed"
    finally:
        conn.close()
