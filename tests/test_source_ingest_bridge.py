"""Job-scoped workspace worker bridge (worker → Fleet without admin bearer)."""

from __future__ import annotations

from fleet_server import store


def test_workspace_worker_bridge_token_and_progress(tmp_path: Path) -> None:
    db = tmp_path / "bridge.sqlite"
    conn = store.connect(db)
    try:
        tok = "bridge-secret-test"
        meta = {
            "container_class": "docker_argv_workspace",
            "workspace_worker_token": tok,
            "workspace_worker_bundle": {"argv": ["echo", "hi"], "cwd": "/tmp"},
        }
        jid = store.insert_job(
            conn,
            kind="docker_argv",
            argv=["docker", "run", "--rm", "alpine", "true"],
            session_id="s",
            meta=meta,
        )
        row, err = store.authenticate_workspace_worker_bridge(conn, jid, tok)
        assert err is None and row is not None

        row_bad, err_bad = store.authenticate_workspace_worker_bridge(conn, jid, "wrong")
        assert row_bad is None and err_bad == "unauthorized"

        store.merge_worker_progress(conn, jid, {"pct": 42, "phase_label": "subprocess", "message": "x"})
        row2 = store.get_job(conn, jid)
        assert isinstance(row2, dict)
        wp = row2.get("worker_progress")
        assert isinstance(wp, dict)
        assert wp.get("pct") == 42
        assert wp.get("message") == "x"

        store.set_worker_result(conn, jid, {"ok": True, "result": {"returncode": 0}, "message": "done"})
        row3 = store.get_job(conn, jid)
        wr = row3.get("worker_result")
        assert isinstance(wr, dict) and wr.get("ok") is True
    finally:
        conn.close()


def test_authenticate_forbidden_without_bridge_token(tmp_path: Path) -> None:
    db = tmp_path / "bridge2.sqlite"
    conn = store.connect(db)
    try:
        jid = store.insert_job(
            conn,
            kind="docker_argv",
            argv=["/bin/true"],
            session_id="s",
            meta={"container_class": "host_cpu_probe"},
        )
        row, err = store.authenticate_workspace_worker_bridge(conn, jid, "any")
        assert row is None and err == "forbidden"
    finally:
        conn.close()
