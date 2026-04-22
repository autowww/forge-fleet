"""Recent jobs list paging (admin snapshot)."""

from __future__ import annotations

from pathlib import Path

from fleet_server import store


def test_count_jobs_and_list_jobs_summary_offset(tmp_path: Path) -> None:
    db = tmp_path / "p.sqlite"
    conn = store.connect(db)
    try:
        for _ in range(15):
            store.insert_job(
                conn,
                kind="docker_argv",
                argv=["docker", "version"],
                session_id="sess",
                meta={"container_class": "host_cpu_probe"},
            )
    finally:
        conn.close()

    conn = store.connect(db)
    try:
        assert store.count_jobs(conn) == 15
        first = store.list_jobs_summary(conn, limit=10, offset=0)
        second = store.list_jobs_summary(conn, limit=10, offset=10)
        assert len(first) == 10
        assert len(second) == 5
        ids = {r["id"] for r in first} | {r["id"] for r in second}
        assert len(ids) == 15
    finally:
        conn.close()
