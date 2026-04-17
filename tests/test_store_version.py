"""SQLite ``fleet_schema`` row tracks package semver + DB schema version."""

from __future__ import annotations

from pathlib import Path

from fleet_server import store, versioning


def test_fleet_schema_row_created(tmp_path: Path) -> None:
    db = tmp_path / "f.sqlite"
    conn = store.connect(db)
    try:
        row = store.get_fleet_version_row(conn)
        assert int(row["db_schema_version"]) == int(versioning.FLEET_DB_SCHEMA_VERSION)
        assert row["package_semver"] == versioning.package_semver()
    finally:
        conn.close()


def test_fleet_schema_survives_second_connect(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    c1 = store.connect(db)
    c1.close()
    c2 = store.connect(db)
    try:
        row = store.get_fleet_version_row(c2)
        assert row["package_semver"]
    finally:
        c2.close()
