"""Unit tests for ``fleet_server.migration_jobs`` argv templates."""

from __future__ import annotations

import pytest

from fleet_server import migration_jobs

_RECIPE_META = {
    "app_image": "example-app:cutover",
    "migrate_argv": ["python", "tools/migrate.py", "--all"],
    "database_url_env": "APP_DATABASE_URL",
    "database_url": "postgresql://u:p@postgres:5432/app",
    "data_volume": "example_app_data",
    "data_mount": "/app/data",
    "docker_network": "example_default",
    "compose_root": "/tmp/example-compose",
    "compose_files": ["compose.yaml", "compose.granite.yaml"],
}


def test_migrate_db_argv_uses_recipe_meta(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    argv = migration_jobs.build_argv_for_step(
        "migrate_db",
        migration_id="mig-1",
        step_id="step-1",
        bundle_extracted=bundle,
        meta=_RECIPE_META,
    )
    assert "example-app:cutover" in argv
    assert "tools/migrate.py" in argv
    assert "--all" in argv
    assert any(a.startswith("APP_DATABASE_URL=") for a in argv)
    assert "example_app_data:/app/data" in argv
    assert "--network" in argv
    assert "example_default" in argv
    assert "/migration/stub.sh" not in argv
    assert "alpine" not in argv
    assert "forge-market" not in " ".join(argv)
    assert "migrate_sqlite_to_postgres.py" not in argv


def test_migrate_db_argv_requires_recipe_image(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    with pytest.raises(ValueError, match="app_image"):
        migration_jobs.build_argv_for_step(
            "migrate_db",
            migration_id="mig-2",
            step_id="step-2",
            bundle_extracted=bundle,
            meta={"migrate_argv": ["true"], "database_url": "postgresql://x"},
        )


def test_migrate_db_argv_requires_database_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.delenv("FLEET_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="database URL"):
        migration_jobs.build_argv_for_step(
            "migrate_db",
            migration_id="mig-3",
            step_id="step-3",
            bundle_extracted=bundle,
            meta={
                "app_image": "example-app:cutover",
                "migrate_argv": ["true"],
                "database_url_env": "APP_DATABASE_URL",
            },
        )


def test_seed_volume_mounts_recipe_volume(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    argv = migration_jobs.build_argv_for_step(
        "seed_corpus_volume",
        migration_id="mig-4",
        step_id="step-4",
        bundle_extracted=bundle,
        meta={"data_volume": "example_app_data"},
    )
    assert "alpine:3.20" in argv
    assert "/migration/stub.sh" in argv
    assert "example_app_data:/seed-target" in argv
    assert any("/migration/bundle" in a for a in argv)


def test_deploy_service_runs_compose(tmp_path) -> None:
    compose = tmp_path / "compose.yaml"
    compose.write_text("name: example\n", encoding="utf-8")
    argv = migration_jobs.build_argv_for_step(
        "deploy_service",
        migration_id="mig-5",
        step_id="step-5",
        bundle_extracted=None,
        meta={"compose_root": str(tmp_path), "compose_files": ["compose.yaml"]},
    )
    assert argv[:2] == ["docker", "compose"]
    assert "-f" in argv
    assert "up" in argv
    assert "-d" in argv
    assert "alpine" not in argv
